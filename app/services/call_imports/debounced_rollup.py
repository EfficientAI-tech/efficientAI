"""Debounced catalog rollup for call-import row completions."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

import redis
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings

_ROLLUP_LOCK_TTL_SECONDS = 10
_rollup_redis: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _rollup_redis
    if _rollup_redis is None:
        _rollup_redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _rollup_redis


def _rollup_lock_key(call_import_id: UUID) -> str:
    return f"import:rollup:lock:{call_import_id}"


def _trailing_rollup_key(call_import_id: UUID) -> str:
    return f"import:rollup:trail:{call_import_id}"


def _schedule_trailing_import_rollup(call_import_id: UUID) -> None:
    """Run a forced rollup after the debounce window when the lock was held."""
    try:
        if not _redis().set(
            _trailing_rollup_key(call_import_id),
            "1",
            nx=True,
            ex=_ROLLUP_LOCK_TTL_SECONDS + 5,
        ):
            return
    except redis.RedisError as exc:
        logger.debug("import trailing rollup dedupe skipped: {}", exc)
    try:
        from app.workers.config import celery_app

        celery_app.send_task(
            "deferred_call_import_rollup",
            args=[str(call_import_id)],
            countdown=_ROLLUP_LOCK_TTL_SECONDS + 1,
            queue="import-control",
        )
    except Exception as exc:
        logger.debug("import trailing rollup enqueue failed: {}", exc)


def platform_discovery_blocks_terminal_status(call_import) -> bool:
    if (getattr(call_import, "source_format", None) or "").lower() != "platform":
        return False
    discovery = (getattr(call_import, "discovery_status", None) or "").strip().lower()
    return discovery in {"queued", "running"}


def maybe_record_import_row_transition(
    call_import_id: UUID,
    *,
    previous_status: Optional[str],
    new_status: Optional[str],
) -> None:
    if previous_status is None or new_status is None:
        return
    prev = str(getattr(previous_status, "value", previous_status)).strip().lower()
    new = str(getattr(new_status, "value", new_status)).strip().lower()
    if prev == new:
        return
    from app.services.call_imports.progress_counters import (
        record_import_row_status_transition,
    )

    record_import_row_status_transition(
        call_import_id,
        previous_status=prev,
        new_status=new,
    )


def schedule_debounced_import_rollup(
    db: Session,
    call_import,
    *,
    force: bool = False,
) -> None:
    """Flush Redis deltas and optionally run full status aggregate."""
    from app.models.database import CallImport
    from app.services.call_imports.bulk_ops import rollup_call_import_batch_status
    from app.services.call_imports.progress_counters import flush_import_progress_to_catalog

    cid = call_import.id if hasattr(call_import, "id") else call_import
    if not isinstance(cid, UUID):
        cid = UUID(str(cid))

    flush_import_progress_to_catalog(db, cid)

    if platform_discovery_blocks_terminal_status(call_import):
        from app.models.enums import CallImportStatus

        if call_import.status != CallImportStatus.DELETING:
            call_import.status = CallImportStatus.PROCESSING
        return

    should_aggregate = force
    if not should_aggregate:
        try:
            should_aggregate = bool(
                _redis().set(
                    _rollup_lock_key(cid),
                    "1",
                    nx=True,
                    ex=_ROLLUP_LOCK_TTL_SECONDS,
                )
            )
        except redis.RedisError as exc:
            logger.debug("import rollup lock skipped: {}", exc)
            should_aggregate = True

    if not should_aggregate:
        _schedule_trailing_import_rollup(cid)
        return

    parent = db.query(CallImport).filter(CallImport.id == cid).first()
    if parent is None:
        return
    rollup_call_import_batch_status(db, parent)
