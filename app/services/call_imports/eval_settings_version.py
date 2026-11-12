"""Redis settings-version counter for call-import evaluations.

Eval workers cache the parent evaluation's settings per process (see
``load_evaluation_snapshot``) keyed by ``eval:settings_ver:{evaluation_id}``.
Any change to a column the worker reads bumps the counter, so the next row in
every worker process reloads once from the catalog.

Bumps happen automatically through an ORM hook: when a session commits after
flushing a ``CallImportEvaluation`` whose watched columns changed (or that was
deleted), the ids are bumped after the commit. Core ``update()`` statements
bypass the ORM, so any new Core writer of a watched column must call
``bump_settings_version`` itself. Today's Core writers only touch counters and
the progress fence, which the worker does not depend on.
"""

from __future__ import annotations

from typing import Iterable, Optional
from uuid import UUID

import redis
from loguru import logger
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

_KEY_TTL_SECONDS = 14 * 24 * 3600
_SESSION_INFO_KEY = "eval_settings_bump"

# Columns the eval worker reads that are not progress counters. Counter
# columns (completed/failed/total/billed rows) are excluded on purpose: the
# Redis-down rollup writes them per row and must not invalidate every cache.
WATCHED_ATTRIBUTES = frozenset(
    {
        "status",
        "started_at",
        "finished_at",
        "error_message",
        "selected_metric_ids",
        "discover_new_metrics",
        "discovered_metric_aliases",
        "discovered_label_aliases",
        "metric_llm_overrides",
        "llm_provider",
        "llm_model",
        "llm_credential_id",
        "llm_config",
        "transcript_source",
        "organization_id",
        "workspace_id",
        "call_import_id",
    }
)


def settings_version_key(evaluation_id: UUID | str) -> str:
    return f"eval:settings_ver:{evaluation_id}"


def _client() -> redis.Redis:
    # Same fail-fast client (and test isolation) as the progress buffer.
    from app.services.call_imports.eval_progress_buffer import _client as buffer_client

    return buffer_client()


def read_settings_version(evaluation_id: UUID | str) -> Optional[int]:
    """Current version (0 when never bumped). ``None`` when Redis is down."""
    try:
        raw = _client().get(settings_version_key(evaluation_id))
    except redis.RedisError as exc:
        logger.debug("eval settings version read failed for {}: {}", evaluation_id, exc)
        return None
    try:
        return int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


def bump_settings_version(evaluation_ids: Iterable[UUID | str]) -> None:
    ids = {str(eid) for eid in evaluation_ids if eid is not None}
    if not ids:
        return
    try:
        pipe = _client().pipeline(transaction=False)
        for eid in ids:
            key = settings_version_key(eid)
            pipe.incr(key)
            pipe.expire(key, _KEY_TTL_SECONDS)
        pipe.execute()
    except redis.RedisError as exc:
        # Workers fall back to a short cache TTL; nothing else to do here.
        logger.warning("eval settings version bump failed for {}: {}", sorted(ids), exc)


def _is_evaluation(obj) -> bool:
    from app.models.database import CallImportEvaluation

    return isinstance(obj, CallImportEvaluation)


def _watched_change(obj) -> bool:
    state = inspect(obj)
    for name in WATCHED_ATTRIBUTES:
        attr = state.attrs.get(name)
        if attr is not None and attr.history.has_changes():
            return True
    return False


def _after_flush(session: Session, _flush_context) -> None:
    pending: set = session.info.get(_SESSION_INFO_KEY) or set()
    for obj in session.deleted:
        if _is_evaluation(obj) and obj.id is not None:
            pending.add(obj.id)
    for obj in session.dirty:
        if _is_evaluation(obj) and obj.id is not None and _watched_change(obj):
            pending.add(obj.id)
    if pending:
        session.info[_SESSION_INFO_KEY] = pending


def _after_commit(session: Session) -> None:
    pending = session.info.pop(_SESSION_INFO_KEY, None)
    if pending:
        bump_settings_version(pending)


def _after_rollback(session: Session) -> None:
    session.info.pop(_SESSION_INFO_KEY, None)


_registered = False


def register_settings_version_hooks() -> None:
    global _registered
    if _registered:
        return
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)
    _registered = True
