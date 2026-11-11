"""Redis version counter for an organization's LLM credentials and gateway settings.

The LLM call path caches, per worker process, the org's gateway settings and
the resolved ``AIProvider`` / ``Integration`` rows, keyed by
``llmcfg:ver:{organization_id}``. Any committed change to those rows (or to
``organizations.llm_gateway_settings`` / ``is_active``) bumps the version, so
every process re-resolves on its next call.

Bumps happen automatically through an ORM hook (``after_flush`` collects,
``after_commit`` bumps, ``after_rollback`` discards). Core / bulk updates
bypass the ORM: call ``mark_llm_config_changed(session, org_id)`` next to
them (``clear_other_defaults`` does). Decrypted secrets are never cached.

Reads are memoized in-process for ``_VERSION_MEMO_SECONDS`` so Redis sees
about one GET per org per second per process. A bump made in this process
clears its own memo immediately; other processes see it within that window.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Iterable, Optional, Tuple
from uuid import UUID

import redis
from loguru import logger
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.config import settings

_KEY_TTL_SECONDS = 14 * 24 * 3600
_SESSION_INFO_KEY = "llm_config_bump"
_ORG_WATCHED_ATTRIBUTES = ("llm_gateway_settings", "is_active")

_memo: Dict[str, Tuple[float, int]] = {}
_memo_lock = threading.Lock()


def _version_memo_seconds() -> float:
    try:
        return max(0.0, float(getattr(settings, "LLM_CONFIG_VERSION_MEMO_SECONDS", 1.0)))
    except (TypeError, ValueError):
        return 1.0


def cache_ttl_seconds() -> float:
    try:
        return max(1.0, float(getattr(settings, "LLM_CONFIG_CACHE_TTL_SECONDS", 120.0)))
    except (TypeError, ValueError):
        return 120.0


def version_key(organization_id: UUID | str) -> str:
    return f"llmcfg:ver:{organization_id}"


def _client() -> redis.Redis:
    # Same fail-fast client (and test isolation) as the eval progress buffer.
    from app.services.call_imports.eval_progress_buffer import _client as buffer_client

    return buffer_client()


def read_llm_config_version(organization_id: UUID | str) -> Optional[int]:
    """Current version (0 if never bumped). ``None`` when Redis is down."""
    org = str(organization_id)
    now = time.monotonic()
    window = _version_memo_seconds()
    if window > 0:
        with _memo_lock:
            hit = _memo.get(org)
        if hit is not None and now - hit[0] < window:
            return hit[1]
    try:
        raw = _client().get(version_key(org))
    except Exception as exc:  # noqa: BLE001 - any client failure means "unknown version"
        logger.debug("llm config version read failed for org {}: {}", org, exc)
        return None
    try:
        value = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        value = 0
    if window > 0:
        with _memo_lock:
            _memo[org] = (now, value)
    return value


def bump_llm_config_version(organization_ids: Iterable[UUID | str]) -> None:
    orgs = {str(org) for org in organization_ids if org is not None}
    if not orgs:
        return
    with _memo_lock:
        for org in orgs:
            _memo.pop(org, None)
    try:
        pipe = _client().pipeline(transaction=False)
        for org in orgs:
            key = version_key(org)
            pipe.incr(key)
            pipe.expire(key, _KEY_TTL_SECONDS)
        pipe.execute()
    except Exception as exc:  # noqa: BLE001
        # Runs from SQLAlchemy's after_commit hook: the commit already
        # succeeded, so a cache-invalidation failure must never surface
        # as an error to the caller. Catch beyond RedisError (e.g. socket
        # setup errors) for that reason.
        logger.warning(
            "llm config version bump failed for orgs {} (stale for up to {}s): {}",
            sorted(orgs),
            int(cache_ttl_seconds()),
            exc,
        )


def clear_version_memo() -> None:
    with _memo_lock:
        _memo.clear()


def mark_llm_config_changed(session: Session, organization_id: UUID | str | None) -> None:
    """Bump this org's version when ``session`` commits (for Core/bulk writes)."""
    if organization_id is None:
        return
    pending: set = session.info.setdefault(_SESSION_INFO_KEY, set())
    pending.add(str(organization_id))


def _credential_models():
    from app.models.database import AIProvider, Integration

    return (AIProvider, Integration)


def _org_watched_change(obj) -> bool:
    state = inspect(obj)
    for name in _ORG_WATCHED_ATTRIBUTES:
        attr = state.attrs.get(name)
        if attr is not None and attr.history.has_changes():
            return True
    return False


def _after_flush(session: Session, _flush_context) -> None:
    from app.models.database import Organization

    credential_models = _credential_models()
    pending: set = session.info.get(_SESSION_INFO_KEY) or set()
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        if isinstance(obj, credential_models):
            if obj in session.dirty and not session.is_modified(obj):
                continue
            org_id = getattr(obj, "organization_id", None)
            if org_id is not None:
                pending.add(str(org_id))
        elif isinstance(obj, Organization) and obj.id is not None:
            if obj in session.deleted or _org_watched_change(obj):
                pending.add(str(obj.id))
    if pending:
        session.info[_SESSION_INFO_KEY] = pending


def _after_commit(session: Session) -> None:
    pending = session.info.pop(_SESSION_INFO_KEY, None)
    if pending:
        bump_llm_config_version(pending)


def _after_rollback(session: Session) -> None:
    session.info.pop(_SESSION_INFO_KEY, None)


_registered = False


def register_llm_config_version_hooks() -> None:
    global _registered
    if _registered:
        return
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)
    _registered = True
