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
    acquire_import_slot,
    read_import_global_inflight,
    release_import_slot_for_celery_task,
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
    if not acquire_import_slot(
        workspace_id=call_import.workspace_id,
        organization_id=call_import.organization_id,
        celery_task_id=reserved_task_id,
    ):
        # #region agent log
        try:
            import json
            import time
            from pathlib import Path

            with (
                Path(__file__).resolve().parents[3] / "debug-6d5466.log"
            ).open("a", encoding="utf-8") as _h:
                _h.write(
                    json.dumps(
                        {
                            "sessionId": "6d5466",
                            "timestamp": int(time.time() * 1000),
                            "location": "import_dispatch.py:at_capacity",
                            "message": "import dispatch at capacity",
                            "data": {
                                "row_id": str(row.id),
                                "import_global_inflight": read_import_global_inflight(),
                            },
                            "hypothesisId": "H2",
                            "runId": "pre-fix",
                        }
                    )
                    + "\n"
                )
        except Exception:
            pass
        # #endregion
        return "at_capacity"

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

    # #region agent log
    try:
        import json
        import time
        from pathlib import Path

        with (Path(__file__).resolve().parents[3] / "debug-6d5466.log").open(
            "a", encoding="utf-8"
        ) as _h:
            _h.write(
                json.dumps(
                    {
                        "sessionId": "6d5466",
                        "timestamp": int(time.time() * 1000),
                        "location": "import_dispatch.py:dispatched",
                        "message": "import row dispatched",
                        "data": {
                            "row_id": str(row.id),
                            "provider": (call_import.provider or "").lower(),
                            "import_global_inflight": read_import_global_inflight(),
                        },
                        "hypothesisId": "H2",
                        "runId": "pre-fix",
                    }
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion

    return "dispatched"
