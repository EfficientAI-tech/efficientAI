"""Fair dispatch for platform historical import rows."""

from __future__ import annotations

from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.database import CallImport, CallImportDiscoverySlice, CallImportRow, Workspace
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.workers.concurrency.fair_import_dispatch import (
    _schedule_import_dispatch_deduped,
    schedule_fair_import_dispatch,
)
from app.workers.config import celery_app

# Use the same queue as CSV call-import workers so local/docker setups that
# already run ``imports`` do not need a separate consumer (legacy tasks may
# still sit on the ``platform-imports`` Redis list — keep that on the worker -Q).
PLATFORM_IMPORTS_QUEUE = "imports"
_BOOTSTRAP_DEDUPE_KEY = "platform_import:discovery_bootstrap"
_BOOTSTRAP_DEDUPE_SECONDS = 45


def schedule_platform_discovery_bootstrap(*, countdown: int = 0) -> None:
    """Enqueue at most one global discovery bootstrap per short window."""
    try:
        import redis

        from app.config import settings

        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        if not client.set(_BOOTSTRAP_DEDUPE_KEY, "1", nx=True, ex=_BOOTSTRAP_DEDUPE_SECONDS):
            return
    except Exception as exc:
        logger.debug("platform discovery bootstrap dedupe skipped: {}", exc)

    try:
        discover_platform_slice_task.apply_async(
            kwargs={"bootstrap": True},
            queue=PLATFORM_IMPORTS_QUEUE,
            countdown=countdown,
        )
    except Exception as exc:
        logger.warning("Failed to schedule platform discovery bootstrap: {}", exc)


def _schedule_pending_slices_for_import(
    db: Session,
    call_import_id: UUID,
    *,
    limit: int = 2,
) -> int:
    rows = (
        db.query(CallImportDiscoverySlice)
        .filter(
            CallImportDiscoverySlice.call_import_id == call_import_id,
            CallImportDiscoverySlice.status == "pending",
        )
        .order_by(CallImportDiscoverySlice.slice_id.asc())
        .limit(limit)
        .all()
    )
    for slice_row in rows:
        discover_platform_slice_task.apply_async(
            kwargs={
                "call_import_id": str(call_import_id),
                "slice_id": slice_row.slice_id,
            },
            queue=PLATFORM_IMPORTS_QUEUE,
        )
    return len(rows)


def _platform_call_imports_with_pending(db: Session, workspace_id: UUID):
    rows = (
        db.query(CallImport.id)
        .join(CallImportRow, CallImportRow.call_import_id == CallImport.id)
        .filter(
            CallImport.workspace_id == workspace_id,
            CallImport.status != CallImportStatus.DELETING,
            CallImport.source_format == "platform",
            CallImport.paused_at.is_(None),
            CallImportRow.status == CallImportRowStatus.PENDING,
            CallImportRow.celery_task_id.is_(None),
        )
        .distinct()
        .all()
    )
    return sorted({row[0] for row in rows if row[0] is not None})


def schedule_fair_platform_import_dispatch(*, countdown: int = 0) -> None:
    try:
        dispatch_fair_platform_import_rows_task.apply_async(
            queue=PLATFORM_IMPORTS_QUEUE,
            countdown=countdown,
        )
    except Exception as exc:
        logger.warning("Failed to schedule platform import dispatch: {}", exc)


@celery_app.task(name="dispatch_fair_platform_import_rows", queue=PLATFORM_IMPORTS_QUEUE)
def dispatch_fair_platform_import_rows_task() -> dict:
    from app.workers.concurrency.platform_import_dispatch import (
        try_dispatch_platform_import_row,
    )

    db = SessionLocal()
    dispatched = 0
    try:
        from app.workers.concurrency.platform_import_dispatch import (
            reclaim_stale_platform_import_dispatches,
        )

        reclaim_stale_platform_import_dispatches(db)

        workspaces = (
            db.query(CallImport.workspace_id)
            .join(CallImportRow, CallImportRow.call_import_id == CallImport.id)
            .join(Workspace, Workspace.id == CallImport.workspace_id)
            .filter(
                CallImport.source_format == "platform",
                CallImport.status != CallImportStatus.DELETING,
                CallImport.paused_at.is_(None),
                CallImportRow.status == CallImportRowStatus.PENDING,
                CallImportRow.celery_task_id.is_(None),
                Workspace.is_active.is_(True),
            )
            .distinct()
            .all()
        )
        for (workspace_id,) in workspaces:
            if workspace_id is None:
                continue
            for call_import_id in _platform_call_imports_with_pending(db, workspace_id):
                row = (
                    db.query(CallImportRow, CallImport)
                    .join(CallImport, CallImport.id == CallImportRow.call_import_id)
                    .filter(
                        CallImport.id == call_import_id,
                        CallImportRow.status == CallImportRowStatus.PENDING,
                        CallImportRow.celery_task_id.is_(None),
                    )
                    .order_by(CallImportRow.created_at.asc())
                    .first()
                )
                if row is None:
                    continue
                import_row, call_import = row
                if try_dispatch_platform_import_row(
                    db=db, row=import_row, call_import=call_import
                ):
                    dispatched += 1
        return {"status": "ok", "dispatched": dispatched}
    finally:
        db.close()


@celery_app.task(name="discover_platform_slice", queue=PLATFORM_IMPORTS_QUEUE, bind=True)
def discover_platform_slice_task(
    self,
    call_import_id: str | None = None,
    slice_id: int | None = None,
    bootstrap: bool = False,
):
    from app.config import settings
    from app.models.database import CallImportDiscoverySlice
    from app.services.call_imports.platform_discovery import discover_platform_slice_chunk

    if call_import_id is not None and not bootstrap:
        logger.info(
            "platform import discovery slice import={} slice={}",
            call_import_id,
            slice_id,
        )

    db = SessionLocal()
    try:
        if bootstrap:
            from datetime import datetime, timedelta, timezone

            stale_cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=settings.PLATFORM_IMPORT_DISCOVERY_SLICE_STALE_MINUTES
            )
            stale_running = (
                db.query(CallImportDiscoverySlice)
                .join(CallImport, CallImport.id == CallImportDiscoverySlice.call_import_id)
                .filter(
                    CallImport.source_format == "platform",
                    CallImportDiscoverySlice.status == "running",
                    CallImportDiscoverySlice.updated_at < stale_cutoff,
                )
                .limit(8)
                .all()
            )
            if stale_running:
                for slice_row in stale_running:
                    slice_row.status = "pending"
                db.commit()

            pending_slices = (
                db.query(CallImportDiscoverySlice)
                .join(CallImport, CallImport.id == CallImportDiscoverySlice.call_import_id)
                .filter(
                    CallImport.source_format == "platform",
                    CallImportDiscoverySlice.status == "pending",
                )
                .limit(4)
                .all()
            )
            scheduled = 0
            for slice_row in pending_slices:
                discover_platform_slice_task.apply_async(
                    kwargs={
                        "call_import_id": str(slice_row.call_import_id),
                        "slice_id": slice_row.slice_id,
                    },
                    queue=PLATFORM_IMPORTS_QUEUE,
                    priority=3,
                )
                scheduled += 1
            if scheduled:
                logger.info("platform import discovery bootstrap scheduled={}", scheduled)
            return {"bootstrapped": scheduled}

        if call_import_id is None or slice_id is None:
            return {"status": "skipped"}

        more = discover_platform_slice_chunk(
            db,
            UUID(call_import_id),
            slice_id,
            page_budget=settings.PLATFORM_IMPORT_DISCOVERY_PAGE_BUDGET,
        )
        if more:
            discover_platform_slice_task.apply_async(
                kwargs={"call_import_id": call_import_id, "slice_id": slice_id},
                queue=PLATFORM_IMPORTS_QUEUE,
                countdown=1,
            )
        else:
            import_id = UUID(call_import_id)
            _schedule_pending_slices_for_import(db, import_id, limit=2)
            schedule_fair_platform_import_dispatch(countdown=1)
        return {"more": more}
    finally:
        db.close()
