"""Copilot persistence: sessions and messages.

A turn is two rows: the user message and the assistant reply. The reply row is
created up front as ``streaming`` so a reconnecting client can find it, and is
finished in one UPDATE when the turn ends. Tool rounds live in its ``steps``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.database import CopilotMessage, CopilotSession

STATUS_STREAMING = "streaming"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_INTERRUPTED = "interrupted"  # read-time only: the worker died mid-turn

TITLE_CHARS = 80
# Older turns are replayed as text only; recent ones include their tool rounds.
REPLAY_TOOL_ROUNDS_FOR_LAST_TURNS = 3
REPLAY_TOOL_RESULT_CHARS = 2_000


class SessionNotFound(LookupError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    title: Optional[str] = None,
) -> CopilotSession:
    now = _now()
    row = CopilotSession(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        title=(title or "").strip()[:200] or None,
        status="active",
        draft={},
        message_count=0,
        last_message_at=now,  # never NULL, so recency ordering is index-only
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_session(
    db: Session, session_id: UUID, *, organization_id: UUID, workspace_id: UUID, user_id: UUID
) -> CopilotSession:
    row = (
        db.query(CopilotSession)
        .filter(
            CopilotSession.id == session_id,
            CopilotSession.organization_id == organization_id,
            CopilotSession.workspace_id == workspace_id,
            CopilotSession.user_id == user_id,
        )
        .first()
    )
    if row is None:
        raise SessionNotFound(str(session_id))
    return row


def encode_cursor(when: datetime, row_id: UUID) -> str:
    return base64.urlsafe_b64encode(f"{when.isoformat()}|{row_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        when, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(when), UUID(row_id)
    except Exception as exc:
        raise ValueError("invalid cursor") from exc


def list_sessions(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    status: str = "active",
    limit: int = 20,
    cursor: Optional[str] = None,
) -> tuple[list[CopilotSession], Optional[str]]:
    q = db.query(CopilotSession).filter(
        CopilotSession.user_id == user_id,
        CopilotSession.workspace_id == workspace_id,
        CopilotSession.status == status,
        CopilotSession.organization_id == organization_id,
    )
    if cursor:
        when, row_id = decode_cursor(cursor)
        q = q.filter(
            or_(
                CopilotSession.last_message_at < when,
                and_(CopilotSession.last_message_at == when, CopilotSession.id < row_id),
            )
        )
    rows = (
        q.order_by(CopilotSession.last_message_at.desc(), CopilotSession.id.desc())
        .limit(limit + 1)
        .all()
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].last_message_at, rows[-1].id)
    return rows, next_cursor


@dataclass
class TurnRows:
    user_message: CopilotMessage
    assistant_message: CopilotMessage
    replayed: bool  # True when client_message_id matched an earlier request


def find_turn_by_client_id(
    db: Session, session_id: UUID, client_message_id: UUID
) -> Optional[TurnRows]:
    user_msg = (
        db.query(CopilotMessage)
        .filter(
            CopilotMessage.session_id == session_id,
            CopilotMessage.client_message_id == client_message_id,
        )
        .first()
    )
    if user_msg is None:
        return None
    reply = (
        db.query(CopilotMessage)
        .filter(CopilotMessage.session_id == session_id, CopilotMessage.seq == user_msg.seq + 1)
        .first()
    )
    if reply is None:
        return None
    return TurnRows(user_msg, reply, replayed=True)


def begin_turn(
    db: Session,
    session: CopilotSession,
    *,
    content: str,
    client_message_id: Optional[UUID],
    page_context: Optional[dict[str, Any]],
    assistant_message_id: Optional[UUID] = None,
) -> TurnRows:
    """Reserve two seqs atomically and insert the user message + streaming reply."""
    if client_message_id is not None:
        existing = find_turn_by_client_id(db, session.id, client_message_id)
        if existing is not None:
            return existing

    now = _now()
    title = content.strip().splitlines()[0][:TITLE_CHARS] if content.strip() else None
    seq_top = db.execute(
        update(CopilotSession)
        .where(CopilotSession.id == session.id)
        .values(
            message_count=CopilotSession.message_count + 2,
            last_message_at=now,
            updated_at=now,
            title=CopilotSession.title if session.title else title,
        )
        .returning(CopilotSession.message_count)
    ).scalar_one()
    user_msg = CopilotMessage(
        id=uuid4(),
        session_id=session.id,
        organization_id=session.organization_id,
        seq=seq_top - 1,
        role="user",
        content=content,
        status=STATUS_COMPLETE,
        client_message_id=client_message_id,
        page_context=page_context,
        created_at=now,
        completed_at=now,
    )
    reply = CopilotMessage(
        id=assistant_message_id or uuid4(),
        session_id=session.id,
        organization_id=session.organization_id,
        seq=seq_top,
        role="assistant",
        content="",
        status=STATUS_STREAMING,
        created_at=now,
    )
    db.add_all([user_msg, reply])
    try:
        db.commit()
    except IntegrityError:
        # A concurrent retry with the same client_message_id won the race.
        db.rollback()
        if client_message_id is not None:
            existing = find_turn_by_client_id(db, session.id, client_message_id)
            if existing is not None:
                return existing
        raise
    return TurnRows(user_msg, reply, replayed=False)


def finish_turn(
    db: Session,
    message_id: UUID,
    *,
    content: str,
    steps: list[dict[str, Any]],
    status: str,
    error: Optional[str],
    model: Optional[str],
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    session_id: UUID,
    draft: Optional[dict[str, Any]] = None,
) -> None:
    now = _now()
    db.execute(
        update(CopilotMessage)
        .where(CopilotMessage.id == message_id)
        .values(
            content=content,
            steps=steps or None,
            status=status,
            error=error,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            completed_at=now,
        )
    )
    values: dict[str, Any] = {"last_message_at": now, "updated_at": now}
    if draft is not None:
        values["draft"] = draft
    db.execute(update(CopilotSession).where(CopilotSession.id == session_id).values(**values))
    db.commit()


def add_event(db: Session, session_id: UUID, content: str) -> CopilotMessage:
    """Record something that happened outside a turn (e.g. the user confirmed an action)."""
    now = _now()
    seq = db.execute(
        update(CopilotSession)
        .where(CopilotSession.id == session_id)
        .values(message_count=CopilotSession.message_count + 1, last_message_at=now, updated_at=now)
        .returning(CopilotSession.message_count)
    ).scalar_one()
    row = CopilotMessage(
        id=uuid4(),
        session_id=session_id,
        organization_id=db.query(CopilotSession.organization_id).filter(CopilotSession.id == session_id).scalar(),
        seq=seq,
        role="event",
        content=content,
        status=STATUS_COMPLETE,
        created_at=now,
        completed_at=now,
    )
    db.add(row)
    db.commit()
    return row


def list_messages(
    db: Session, session_id: UUID, *, before_seq: Optional[int] = None, limit: int = 50
) -> tuple[list[CopilotMessage], bool]:
    """Newest ``limit`` messages before ``before_seq``, returned oldest first."""
    q = db.query(CopilotMessage).filter(CopilotMessage.session_id == session_id)
    if before_seq is not None:
        q = q.filter(CopilotMessage.seq < before_seq)
    rows = q.order_by(CopilotMessage.seq.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    return list(reversed(rows[:limit])), has_more


def history_for_llm(db: Session, session_id: UUID, *, up_to_seq: int, limit: int) -> list[dict]:
    """Recent conversation as chat messages, ending with the current user message.

    Unanswered turns (failed with no text) are dropped so roles stay alternating,
    which some providers require.
    """
    rows = (
        db.query(CopilotMessage)
        .filter(CopilotMessage.session_id == session_id, CopilotMessage.seq <= up_to_seq)
        .order_by(CopilotMessage.seq.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    by_seq = {r.seq: r for r in rows}
    assistant_seqs = [r.seq for r in rows if r.role == "assistant" and r.content]
    replay_rounds = set(assistant_seqs[-REPLAY_TOOL_ROUNDS_FOR_LAST_TURNS:])

    out: list[dict] = []
    # Events (confirmations, undos) are folded into the next user message so
    # roles keep alternating user/assistant.
    pending_events: list[str] = []
    for row in rows:
        if row.role == "event":
            pending_events.append(row.content)
            continue
        if row.role == "user":
            reply = by_seq.get(row.seq + 1)
            if row.seq != up_to_seq and (reply is None or not reply.content):
                continue
            content = row.content
            if pending_events:
                notes = "\n".join(f"[Update since your last reply: {e}]" for e in pending_events)
                content = f"{notes}\n\n{content}"
                pending_events = []
            out.append({"role": "user", "content": content})
            continue
        if not row.content:
            continue
        if row.seq in replay_rounds:
            for step in row.steps or []:
                calls = step.get("calls") or []
                if not calls:
                    continue
                # Pre-tool text is already part of row.content; don't replay it twice.
                out.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {"name": c["name"], "arguments": c.get("arguments") or "{}"},
                        }
                        for c in calls
                    ],
                })
                for c in calls:
                    out.append({
                        "role": "tool",
                        "tool_call_id": c["id"],
                        "content": (c.get("content") or "")[:REPLAY_TOOL_RESULT_CHARS],
                    })
        out.append({"role": "assistant", "content": row.content})
    # A window that starts mid-turn must not open with an assistant/tool message.
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out
