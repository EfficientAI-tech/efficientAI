"""Throttled fan-out for call-import recording fetch rows."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from celery.utils import uuid as celery_uuid
from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.workers.concurrency.eval_dispatch import IMPORTS_QUEUE
from app.workers.concurrency.limits import (
    acquire_eval_slot,
    release_eval_slot_for_celery_task,
)

DispatchImportRowResult = Literal["dispatched", "skip", "at_capacity"]


def _try_dispatch_single_import_row(
    *,
    db: Session,
    row: CallImportRow,
    call_import: CallImport,
) -> DispatchImportRowResult:
    from app.workers.tasks.process_call_import_row import (
        process_call_import_row_task,
    )

    if row.status != CallImportRowStatus.PENDING:
        return "skip"
    if row.celery_task_id:
        return "skip"
    if call_import.status == CallImportStatus.DELETING:
        return "skip"

    reserved_task_id = celery_uuid()
    if not acquire_eval_slot(
        workspace_id=call_import.workspace_id,
        organization_id=call_import.organization_id,
        celery_task_id=reserved_task_id,
    ):
        return "at_capacity"

    try:
        async_result = process_call_import_row_task.apply_async(
            args=(str(row.id),),
            kwargs={"_eval_slot_task_id": reserved_task_id},
            queue=IMPORTS_QUEUE,
            task_id=reserved_task_id,
        )
    except Exception:
        release_eval_slot_for_celery_task(reserved_task_id)
        raise

    try:
        row.celery_task_id = async_result.id
        db.commit()
    except Exception:
        release_eval_slot_for_celery_task(reserved_task_id)
        raise

    return "dispatched"
