"""Propose, confirm, reject and undo copilot actions.

State changes use a conditional UPDATE (``WHERE status = 'proposed'``), so a
double click, two open tabs or a retried request can never apply an action
twice. Every outcome is also written into the conversation as an ``event``
message, so the model knows on the next turn what the user confirmed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from loguru import logger
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.database import CopilotAction
from app.services.copilot import store
from app.services.copilot.actions.base import (
    ActionContext,
    ActionResult,
    call_maybe_async,
    get_kind,
)
from app.services.copilot.registry import ToolError, ToolOutput, _strip_titles

PROPOSAL_TTL = timedelta(hours=24)
UNDO_WINDOW = timedelta(hours=24)

STATUS_PROPOSED = "proposed"
STATUS_APPLYING = "applying"
STATUS_APPLIED = "applied"
STATUS_FAILED = "failed"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"
STATUS_UNDOING = "undoing"
STATUS_UNDONE = "undone"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def propose(
    db: Session,
    *,
    kind: str,
    payload: dict[str, Any],
    session_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    message_id: Optional[UUID],
    capabilities: frozenset[str],
) -> ToolOutput:
    """Record a proposal and return what the model and the UI should see."""
    action_kind = get_kind(kind)
    if action_kind is None:
        raise ToolError(f"Unknown action {kind!r}.")
    if action_kind.capability and action_kind.capability not in capabilities:
        raise ToolError("The user doesn't have permission for this in the current workspace.")
    try:
        model = action_kind.payload_model.model_validate(payload)
    except ValidationError as exc:
        raise ToolError(f"Invalid proposal: {exc.errors()[0]['msg']}") from exc
    estimate = (
        action_kind.estimate(db, organization_id, workspace_id, model)
        if action_kind.estimate
        else None
    )
    row = CopilotAction(
        id=uuid4(),
        session_id=session_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        message_id=message_id,
        kind=kind,
        status=STATUS_PROPOSED,
        summary=action_kind.describe(model),
        payload=model.model_dump(mode="json"),
        cost_estimate=estimate,
        created_at=_now(),
        expires_at=_now() + PROPOSAL_TTL,
    )
    db.add(row)
    db.commit()
    return ToolOutput(
        data={
            "status": "awaiting_user_confirmation",
            "action_id": str(row.id),
            "summary": row.summary,
            **({"cost_estimate": estimate} if estimate else {}),
            "note": (
                "Nothing has changed yet. The user sees a card to review, edit and confirm. "
                "Don't say it's done; tell them to confirm the card."
            ),
        },
        ui={"type": "proposal", "action": serialize(row)},
    )


def serialize(row: CopilotAction) -> dict[str, Any]:
    action_kind = get_kind(row.kind)
    status = row.status
    expires = _aware(row.expires_at)
    if status == STATUS_PROPOSED and expires is not None and expires < _now():
        status = STATUS_EXPIRED
    decided = _aware(row.decided_at)
    undoable = bool(
        status == STATUS_APPLIED
        and action_kind is not None
        and action_kind.undo is not None
        and row.undo_state is not None
        and decided is not None
        and _now() - decided < UNDO_WINDOW
    )
    return {
        "id": str(row.id),
        "kind": row.kind,
        "title": action_kind.title if action_kind else row.kind,
        "status": status,
        "summary": row.summary,
        "payload": row.payload or {},
        "payload_schema": (
            _strip_titles(action_kind.payload_model.model_json_schema())
            if action_kind and action_kind.editable
            else None
        ),
        "costly": bool(action_kind and action_kind.costly),
        "cost_estimate": row.cost_estimate,
        "result": row.result,
        "error": row.error,
        "undoable": undoable,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": expires.isoformat() if expires else None,
    }


def get_for_user(db: Session, action_id: UUID, *, user_id: UUID, workspace_id: UUID) -> CopilotAction:
    row = (
        db.query(CopilotAction)
        .filter(
            CopilotAction.id == action_id,
            CopilotAction.user_id == user_id,
            CopilotAction.workspace_id == workspace_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return row


def _transition(db: Session, action_id: UUID, from_status: str, to_status: str, **values: Any) -> bool:
    changed = db.execute(
        update(CopilotAction)
        .where(CopilotAction.id == action_id, CopilotAction.status == from_status)
        .values(status=to_status, **values)
    ).rowcount
    db.commit()
    return bool(changed)


def _error_text(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        return detail if isinstance(detail, str) else str(detail)
    if isinstance(exc, (ValueError, ToolError)):
        return str(exc)
    return "Something went wrong while applying this. Nothing else was changed."


async def confirm(
    db: Session,
    row: CopilotAction,
    *,
    capabilities: frozenset[str],
    edited_payload: Optional[dict[str, Any]] = None,
) -> CopilotAction:
    action_kind = get_kind(row.kind)
    if action_kind is None:
        raise HTTPException(status_code=400, detail="This action is no longer supported.")
    if action_kind.capability and action_kind.capability not in capabilities:
        raise HTTPException(status_code=403, detail="You don't have permission for this in this workspace.")
    expires = _aware(row.expires_at)
    if row.status == STATUS_PROPOSED and expires is not None and expires < _now():
        _transition(db, row.id, STATUS_PROPOSED, STATUS_EXPIRED)
        raise HTTPException(status_code=409, detail="This proposal expired. Ask the assistant again.")

    payload_data = edited_payload if (edited_payload is not None and action_kind.editable) else row.payload
    try:
        payload = action_kind.payload_model.model_validate(payload_data)
    except ValidationError as exc:
        err = exc.errors()[0]
        raise HTTPException(
            status_code=422,
            detail=f"{'.'.join(str(p) for p in err['loc']) or 'payload'}: {err['msg']}",
        )

    if not _transition(
        db, row.id, STATUS_PROPOSED, STATUS_APPLYING,
        decided_at=_now(), payload=payload.model_dump(mode="json"), summary=action_kind.describe(payload),
    ):
        db.refresh(row)
        raise HTTPException(status_code=409, detail=f"This action is already {row.status}.")

    ctx = ActionContext(
        db=db,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        user_id=row.user_id,
        capabilities=capabilities,
    )
    try:
        result: ActionResult = await call_maybe_async(action_kind.apply, ctx, payload)
    except Exception as exc:
        db.rollback()
        if not isinstance(exc, (HTTPException, ValueError, ToolError)):
            logger.exception("[Copilot] action {} ({}) failed", row.id, row.kind)
        message = _error_text(exc)
        _transition(db, row.id, STATUS_APPLYING, STATUS_FAILED, error=message)
        store.add_event(db, row.session_id, f"Tried to apply \"{action_kind.title}\" but it failed: {message}")
        db.refresh(row)
        return row

    _transition(
        db, row.id, STATUS_APPLYING, STATUS_APPLIED,
        result=result.as_dict(), undo_state=result.undo_state,
    )
    store.add_event(db, row.session_id, f"The user confirmed \"{action_kind.title}\". {result.summary}")
    db.refresh(row)
    return row


def reject(db: Session, row: CopilotAction) -> CopilotAction:
    if not _transition(db, row.id, STATUS_PROPOSED, STATUS_REJECTED, decided_at=_now()):
        db.refresh(row)
        raise HTTPException(status_code=409, detail=f"This action is already {row.status}.")
    action_kind = get_kind(row.kind)
    title = action_kind.title if action_kind else row.kind
    store.add_event(db, row.session_id, f"The user rejected \"{title}\" ({row.summary}). Nothing was changed.")
    db.refresh(row)
    return row


async def undo(db: Session, row: CopilotAction, *, capabilities: frozenset[str]) -> CopilotAction:
    state = serialize(row)
    if not state["undoable"]:
        raise HTTPException(status_code=409, detail="This action can't be undone.")
    action_kind = get_kind(row.kind)
    assert action_kind is not None and action_kind.undo is not None
    if action_kind.capability and action_kind.capability not in capabilities:
        raise HTTPException(status_code=403, detail="You don't have permission for this in this workspace.")
    if not _transition(db, row.id, STATUS_APPLIED, STATUS_UNDOING):
        db.refresh(row)
        raise HTTPException(status_code=409, detail=f"This action is already {row.status}.")
    ctx = ActionContext(
        db=db,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        user_id=row.user_id,
        capabilities=capabilities,
    )
    try:
        await call_maybe_async(action_kind.undo, ctx, row.undo_state or {})
    except Exception as exc:
        db.rollback()
        if not isinstance(exc, (HTTPException, ValueError, ToolError)):
            logger.exception("[Copilot] undo of {} failed", row.id)
        # Back to applied: the change is still in place.
        _transition(db, row.id, STATUS_UNDOING, STATUS_APPLIED)
        raise HTTPException(status_code=409, detail=f"Couldn't undo: {_error_text(exc)}")
    _transition(db, row.id, STATUS_UNDOING, STATUS_UNDONE, undone_at=_now())
    store.add_event(db, row.session_id, f"The user undid \"{action_kind.title}\" ({row.summary}).")
    db.refresh(row)
    return row
