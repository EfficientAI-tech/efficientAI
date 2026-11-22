"""In-app copilot (EFF-71): readiness, chat sessions, and streamed replies.

Sessions are private to their user within the active workspace. Sending a
message returns a Server-Sent Events stream:

  turn_started  {session_id, user_message_id, message_id}
  token         {text}
  tool_call     {id, name}
  tool_result   {id, name, status, latency_ms}
  draft         {type: "draft", draft: {...}}      (unsaved generated setup)
  error         {code, message}
  done          {message_id, status, latency_ms, usage}

The turn runs in a worker thread, independent of the connection. If the client
drops, the reply is still saved; GET .../messages returns it (with live content
while it is still streaming).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth import Principal, get_principal
from app.dependencies import WorkspaceContext, get_db, get_workspace_context
from app.models.copilot_schemas import (
    CopilotActionConfirm,
    CopilotMessageCreate,
    CopilotMessageListResponse,
    CopilotMessageResponse,
    CopilotSessionCreate,
    CopilotSessionListResponse,
    CopilotSessionResponse,
    CopilotSessionUpdate,
    CopilotStatusResponse,
    CopilotToolCallView,
)
from app.models.database import CopilotAction, CopilotMessage, CopilotSession
from app.services.copilot.actions import service as actions
from app.services.copilot import redis_state, store
from app.services.copilot.readiness import check_readiness
from app.services.copilot.registry import available_tools
from app.services.copilot.turn import TurnInput, release_slot, submit_turn, try_reserve_slot

router = APIRouter(prefix="/copilot", tags=["copilot"])

HEARTBEAT_SECONDS = 15
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",  # stop nginx from buffering the stream
    "Connection": "keep-alive",
}


def _user_id(principal: Principal) -> UUID:
    if principal.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The assistant needs a signed-in user (API keys without a user can't use it).",
        )
    return principal.user_id


def _session_or_404(db: Session, session_id: UUID, ctx: WorkspaceContext, user_id: UUID) -> CopilotSession:
    try:
        return store.get_session(
            db,
            session_id,
            organization_id=ctx.organization_id,
            workspace_id=ctx.workspace_id,
            user_id=user_id,
        )
    except store.SessionNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")


def _session_response(row: CopilotSession, *, include_draft: bool = False) -> CopilotSessionResponse:
    return CopilotSessionResponse(
        id=row.id,
        title=row.title,
        status=row.status,
        message_count=row.message_count,
        last_message_at=row.last_message_at,
        created_at=row.created_at,
        draft=(row.draft or None) if include_draft else None,
    )


def _message_response(row: CopilotMessage, snapshot: Optional[dict[str, Any]] = None) -> CopilotMessageResponse:
    content, msg_status, steps = row.content, row.status, row.steps or []
    if row.status == store.STATUS_STREAMING:
        if snapshot:
            content = snapshot.get("content") or ""
            msg_status = snapshot.get("status") or msg_status
            steps = snapshot.get("steps") or steps
        else:
            stale_after = timedelta(seconds=settings.COPILOT_TURN_TIMEOUT_SECONDS + 60)
            created = row.created_at
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created is not None and datetime.now(timezone.utc) - created > stale_after:
                msg_status = store.STATUS_INTERRUPTED
    calls = [
        CopilotToolCallView(
            id=c.get("id", ""),
            name=c.get("name", ""),
            status=c.get("status", ""),
            latency_ms=c.get("latency_ms"),
            ui=c.get("ui"),
        )
        for step in steps
        for c in (step.get("calls") or [])
    ]
    return CopilotMessageResponse(
        id=row.id,
        seq=row.seq,
        role=row.role,
        content=content,
        status=msg_status,
        error=row.error,
        tool_calls=calls,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


# --- readiness ---------------------------------------------------------------


@router.get("/status", response_model=CopilotStatusResponse, operation_id="getCopilotStatus")
def copilot_status(
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    _user_id(principal)
    readiness = check_readiness(db, ctx.organization_id)
    return CopilotStatusResponse(
        **readiness.public(),
        tools=[t.name for t in available_tools(ctx.capabilities)] if readiness.ready else [],
    )


# --- sessions ----------------------------------------------------------------


@router.get("/sessions", response_model=CopilotSessionListResponse, operation_id="listCopilotSessions")
def list_sessions(
    session_status: str = Query("active", alias="status", pattern="^(active|archived)$"),
    limit: int = Query(20, ge=1, le=50),
    cursor: Optional[str] = Query(None, max_length=200),
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    try:
        rows, next_cursor = store.list_sessions(
            db,
            organization_id=ctx.organization_id,
            workspace_id=ctx.workspace_id,
            user_id=_user_id(principal),
            status=session_status,
            limit=limit,
            cursor=cursor,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cursor")
    return CopilotSessionListResponse(items=[_session_response(r) for r in rows], next_cursor=next_cursor)


@router.post(
    "/sessions",
    response_model=CopilotSessionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCopilotSession",
)
def create_session(
    data: CopilotSessionCreate,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    row = store.create_session(
        db,
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        user_id=_user_id(principal),
        title=data.title,
    )
    return _session_response(row, include_draft=True)


@router.get("/sessions/{session_id}", response_model=CopilotSessionResponse, operation_id="getCopilotSession")
def get_session(
    session_id: UUID,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    return _session_response(_session_or_404(db, session_id, ctx, _user_id(principal)), include_draft=True)


@router.patch("/sessions/{session_id}", response_model=CopilotSessionResponse, operation_id="updateCopilotSession")
def update_session(
    session_id: UUID,
    data: CopilotSessionUpdate,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    row = _session_or_404(db, session_id, ctx, _user_id(principal))
    if data.title is not None:
        row.title = data.title.strip()[:200] or None
    if data.status is not None:
        row.status = data.status
    db.commit()
    db.refresh(row)
    return _session_response(row, include_draft=True)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteCopilotSession")
def delete_session(
    session_id: UUID,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    row = _session_or_404(db, session_id, ctx, _user_id(principal))
    db.delete(row)  # messages go with it (ON DELETE CASCADE)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- messages ----------------------------------------------------------------


@router.get(
    "/sessions/{session_id}/messages",
    response_model=CopilotMessageListResponse,
    operation_id="listCopilotMessages",
)
def list_messages(
    session_id: UUID,
    before_seq: Optional[int] = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    session_row = _session_or_404(db, session_id, ctx, _user_id(principal))
    rows, has_more = store.list_messages(db, session_row.id, before_seq=before_seq, limit=limit)
    streaming = [r.id for r in rows if r.status == store.STATUS_STREAMING]
    snapshots = redis_state.read_snapshots(streaming)
    return CopilotMessageListResponse(
        items=[_message_response(r, snapshots.get(r.id)) for r in rows],
        has_more=has_more,
    )


@router.post(
    "/sessions/{session_id}/messages/{message_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="cancelCopilotMessage",
)
def cancel_message(
    session_id: UUID,
    message_id: UUID,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    session_row = _session_or_404(db, session_id, ctx, _user_id(principal))
    exists = (
        db.query(CopilotMessage.id)
        .filter(CopilotMessage.id == message_id, CopilotMessage.session_id == session_row.id)
        .first()
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Message not found")
    redis_state.request_cancel(message_id)
    return {"status": "cancelling"}


# --- actions (proposed changes) -------------------------------------------------


@router.get("/sessions/{session_id}/actions", operation_id="listCopilotActions")
def list_actions(
    session_id: UUID,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    session_row = _session_or_404(db, session_id, ctx, _user_id(principal))
    rows = (
        db.query(CopilotAction)
        .filter(CopilotAction.session_id == session_row.id)
        .order_by(CopilotAction.created_at.desc())
        .limit(200)
        .all()
    )
    return {"items": [actions.serialize(r) for r in rows]}


@router.get("/actions/{action_id}", operation_id="getCopilotAction")
def get_action(
    action_id: UUID,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    row = actions.get_for_user(db, action_id, user_id=_user_id(principal), workspace_id=ctx.workspace_id)
    return actions.serialize(row)


@router.post("/actions/{action_id}/confirm", operation_id="confirmCopilotAction")
async def confirm_action(
    action_id: UUID,
    data: CopilotActionConfirm,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    user_id = _user_id(principal)

    def work() -> dict:
        # The action calls existing route handlers that do blocking DB work, so
        # it runs on a worker thread with its own event loop, never the server's.
        row = actions.get_for_user(db, action_id, user_id=user_id, workspace_id=ctx.workspace_id)
        row = asyncio.run(actions.confirm(db, row, capabilities=ctx.capabilities, edited_payload=data.payload))
        return actions.serialize(row)

    return await run_in_threadpool(work)


@router.post("/actions/{action_id}/reject", operation_id="rejectCopilotAction")
def reject_action(
    action_id: UUID,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    row = actions.get_for_user(db, action_id, user_id=_user_id(principal), workspace_id=ctx.workspace_id)
    return actions.serialize(actions.reject(db, row))


@router.post("/actions/{action_id}/undo", operation_id="undoCopilotAction")
async def undo_action(
    action_id: UUID,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    user_id = _user_id(principal)

    def work() -> dict:
        row = actions.get_for_user(db, action_id, user_id=user_id, workspace_id=ctx.workspace_id)
        row = asyncio.run(actions.undo(db, row, capabilities=ctx.capabilities))
        return actions.serialize(row)

    return await run_in_threadpool(work)


class _Prepared:
    def __init__(self, turn: Optional[TurnInput], replay: Optional[dict[str, Any]] = None):
        self.turn = turn
        self.replay = replay


def _prepare_turn(
    db: Session,
    session_id: UUID,
    data: CopilotMessageCreate,
    ctx: WorkspaceContext,
    user_id: UUID,
) -> _Prepared:
    """All checks and the DB insert, cheapest first. Runs in a worker thread."""
    try:
        session_row = _session_or_404(db, session_id, ctx, user_id)
        if session_row.status != "active":
            raise HTTPException(status_code=409, detail="This conversation is archived.")

        if data.client_message_id is not None:
            existing = store.find_turn_by_client_id(db, session_row.id, data.client_message_id)
            if existing is not None:
                return _Prepared(None, {
                    "session_id": str(session_row.id),
                    "user_message_id": str(existing.user_message.id),
                    "message_id": str(existing.assistant_message.id),
                    "status": existing.assistant_message.status,
                })

        readiness = check_readiness(db, ctx.organization_id)
        if not readiness.ready or readiness.llm is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "copilot_not_ready",
                    "reasons": [r.__dict__ for r in readiness.reasons],
                },
            )

        limit = redis_state.check_message_rate(user_id, ctx.organization_id)
        if not limit.allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Too many messages for this {limit.scope}. Try again in {limit.retry_after_seconds}s.",
                headers={"Retry-After": str(limit.retry_after_seconds)},
            )
        if redis_state.org_token_budget_exhausted(ctx.organization_id):
            raise HTTPException(
                status_code=429,
                detail="Your organization has used today's assistant budget. It resets at 00:00 UTC.",
            )

        if not try_reserve_slot():
            raise HTTPException(
                status_code=503,
                detail="The assistant is busy. Try again in a few seconds.",
                headers={"Retry-After": "5"},
            )
        assistant_id = uuid4()
        locked = False
        try:
            if not redis_state.acquire_turn_lock(user_id, assistant_id):
                raise HTTPException(
                    status_code=409,
                    detail="The assistant is still answering your previous message.",
                )
            locked = True
            page_context = data.page_context.model_dump(exclude_none=True) if data.page_context else None
            rows = store.begin_turn(
                db,
                session_row,
                content=data.content,
                client_message_id=data.client_message_id,
                page_context=page_context or None,
                assistant_message_id=assistant_id,
            )
            if rows.replayed:  # lost a race with an identical retry
                redis_state.release_turn_lock(user_id, assistant_id)
                release_slot()
                return _Prepared(None, {
                    "session_id": str(session_row.id),
                    "user_message_id": str(rows.user_message.id),
                    "message_id": str(rows.assistant_message.id),
                    "status": rows.assistant_message.status,
                })
        except BaseException:
            if locked:
                redis_state.release_turn_lock(user_id, assistant_id)
            release_slot()
            raise

        return _Prepared(TurnInput(
            session_id=session_row.id,
            user_message_id=rows.user_message.id,
            user_seq=rows.user_message.seq,
            assistant_message_id=assistant_id,
            organization_id=ctx.organization_id,
            workspace_id=ctx.workspace_id,
            user_id=user_id,
            capabilities=ctx.capabilities,
            timezone=data.timezone or "UTC",
            page_context=page_context or None,
            llm=readiness.llm,
        ))
    finally:
        # Hand the connection back to the pool before streaming (ending the
        # transaction releases it); the turn opens its own sessions.
        db.rollback()


def _sse(event: str, data: dict[str, Any], event_id: int) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/sessions/{session_id}/messages", operation_id="sendCopilotMessage")
async def send_message(
    session_id: UUID,
    data: CopilotMessageCreate,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    if len(data.content) > settings.COPILOT_MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Message is too long (max {settings.COPILOT_MAX_MESSAGE_CHARS} characters).",
        )
    user_id = _user_id(principal)
    prepared = await run_in_threadpool(_prepare_turn, db, session_id, data, ctx, user_id)

    if prepared.turn is None:
        replay = prepared.replay or {}

        async def replayed() -> AsyncIterator[str]:
            yield _sse("turn_started", {**replay, "replayed": True}, 1)
            yield _sse("done", {"message_id": replay.get("message_id"), "status": replay.get("status"), "replayed": True}, 2)

        return StreamingResponse(replayed(), media_type="text/event-stream", headers=_SSE_HEADERS)

    turn = prepared.turn
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

    def emit(event: str, payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, payload))

    submit_turn(turn, emit)

    async def events() -> AsyncIterator[str]:
        event_id = 1
        yield _sse("turn_started", {
            "session_id": str(turn.session_id),
            "user_message_id": str(turn.user_message_id),
            "message_id": str(turn.assistant_message_id),
        }, event_id)
        while True:
            try:
                event, payload = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            event_id += 1
            yield _sse(event, payload, event_id)
            if event == "done":
                return

    return StreamingResponse(events(), media_type="text/event-stream", headers=_SSE_HEADERS)
