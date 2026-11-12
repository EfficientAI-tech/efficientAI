"""Best-effort Celery task revocation from the API / bulk workers."""

from __future__ import annotations

from typing import Iterable, List, Optional

from loguru import logger

_REVOKE_TASK_BATCH = 500


def celery_revoke_use_terminate() -> bool:
    """True only when workers use a pool that supports kill_job (e.g. prefork)."""
    from app.config import settings

    return bool(getattr(settings, "CELERY_REVOKE_USE_TERMINATE", False))


def revoke_celery_tasks(
    task_ids: Iterable[str],
    *,
    terminate: Optional[bool] = None,
) -> int:
    """Revoke task ids in batches.

    ``terminate=None`` (default) follows :func:`celery_revoke_use_terminate`.
    ``terminate=False`` never sends SIGTERM. ``terminate=True`` forces terminate
    (use only when callers know the target worker pool supports it).
    """
    cleaned: List[str] = [tid for tid in task_ids if (tid or "").strip()]
    if not cleaned:
        return 0
    use_terminate = (
        celery_revoke_use_terminate() if terminate is None else bool(terminate)
    )
    try:
        from app.workers.celery_app import celery_app

        revoked = 0
        for start in range(0, len(cleaned), _REVOKE_TASK_BATCH):
            chunk = cleaned[start : start + _REVOKE_TASK_BATCH]
            if use_terminate:
                celery_app.control.revoke(
                    chunk, terminate=True, signal="SIGTERM"
                )
            else:
                celery_app.control.revoke(chunk, terminate=False)
            revoked += len(chunk)
        if not use_terminate and terminate is None:
            logger.debug(
                "Revoked {} Celery task(s) with terminate=False (thread/solo pool)",
                revoked,
            )
        return revoked
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to revoke {} Celery task(s): {}", len(cleaned), exc)
        return 0
