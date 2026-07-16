"""Throttled fan-out for call-import recording fetch rows."""

from __future__ import annotations

from typing import Literal, NamedTuple
from uuid import UUID

from celery.utils import uuid as celery_uuid
from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.workers.concurrency.eval_dispatch import IMPORTS_QUEUE
from app.workers.concurrency.limits import (
    acquire_import_slot,
    read_import_global_inflight,
    release_import_slot_for_celery_task,
)
from app.workers.concurrency.telephony_credential_rate_limit import (
    peek_telephony_import_credit,
    requires_authenticated_recording_fetch,
)

DispatchImportRowResult = Literal[
    "dispatched", "skip", "at_capacity", "credential_throttled"
]


class ImportDispatchOutcome(NamedTuple):
    result: DispatchImportRowResult
    wait_seconds: int = 0


def _peek_authenticated_import_credit(
    *,
    db: Session,
    call_import: CallImport,
) -> ImportDispatchOutcome | None:
    if not requires_authenticated_recording_fetch(call_import):
        return None

    from app.services.telephony.telephony_service import telephony_service

    try:
        integration = telephony_service.get_org_integration(
            call_import.organization_id,
            db,
            provider=call_import.provider,
            credential_id=call_import.telephony_integration_id,
        )
    except Exception as exc:
        logger.warning(
            "Skipping telephony credit peek for import {}: {}",
            call_import.id,
            exc,
        )
        return None

    from app.workers.concurrency.telephony_credential_rate_limit import (
        fingerprint_for_integration,
    )

    credit = peek_telephony_import_credit(fingerprint_for_integration(integration))
    if credit.allowed:
        return None
    return ImportDispatchOutcome(
        "credential_throttled",
        wait_seconds=max(1, credit.wait_seconds),
    )


def _try_dispatch_single_import_row(
    *,
    db: Session,
    row: CallImportRow,
    call_import: CallImport,
) -> ImportDispatchOutcome:
    from app.workers.tasks.process_call_import_row import (
        process_call_import_row_task,
    )

    if row.status != CallImportRowStatus.PENDING:
        return ImportDispatchOutcome("skip")
    if row.celery_task_id:
        return ImportDispatchOutcome("skip")
    if call_import.status == CallImportStatus.DELETING:
        return ImportDispatchOutcome("skip")

    throttled = _peek_authenticated_import_credit(db=db, call_import=call_import)
    if throttled is not None:
        return throttled

    reserved_task_id = celery_uuid()
    if not acquire_import_slot(
        workspace_id=call_import.workspace_id,
        organization_id=call_import.organization_id,
        celery_task_id=reserved_task_id,
    ):
        return ImportDispatchOutcome("at_capacity")

    try:
        async_result = process_call_import_row_task.apply_async(
            args=(str(row.id),),
            kwargs={"_eval_slot_task_id": reserved_task_id},
            queue=IMPORTS_QUEUE,
            task_id=reserved_task_id,
        )
    except Exception:
        release_import_slot_for_celery_task(reserved_task_id)
        raise

    try:
        row.celery_task_id = async_result.id
        db.commit()
    except Exception:
        release_import_slot_for_celery_task(reserved_task_id)
        raise

    logger.debug(
        "Import row {} dispatched (provider={}, global_inflight={})",
        row.id,
        (call_import.provider or "").lower(),
        read_import_global_inflight(),
    )

    return ImportDispatchOutcome("dispatched")
