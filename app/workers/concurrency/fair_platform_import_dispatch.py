"""Fair dispatch for platform historical import rows."""

from __future__ import annotations

from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.database import CallImport, CallImportRow, Workspace
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.workers.concurrency.fair_import_dispatch import (
    _schedule_import_dispatch_deduped,
    schedule_fair_import_dispatch,
)
from app.workers.config import celery_app

PLATFORM_IMPORTS_QUEUE = "platform-imports"


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

    db = SessionLocal()
    try:
        if bootstrap:
            running = (
                db.query(CallImportDiscoverySlice)
                .join(CallImport, CallImport.id == CallImportDiscoverySlice.call_import_id)
                .filter(
                    CallImport.source_format == "platform",
                    CallImportDiscoverySlice.status.in_(("pending", "running")),
                )
                .limit(4)
                .all()
            )
            for slice_row in running:
                discover_platform_slice_task.apply_async(
                    kwargs={
                        "call_import_id": str(slice_row.call_import_id),
                        "slice_id": slice_row.slice_id,
                    },
                    queue=PLATFORM_IMPORTS_QUEUE,
                )
            return {"bootstrapped": len(running)}

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
            discover_platform_slice_task.apply_async(
                kwargs={"bootstrap": True},
                queue=PLATFORM_IMPORTS_QUEUE,
                countdown=2,
            )
        return {"more": more}
    finally:
        db.close()
