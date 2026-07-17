"""Eval fair dispatch with sharded row sessions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.models.enums import CallImportRowStatus
from app.workers.concurrency.eval_dispatch import (
    EvalDispatchOutcome,
    _load_call_import_for_eval_row,
    _try_dispatch_single_row,
)


def test_load_call_import_for_eval_row_uses_catalog_query():
    catalog_db = MagicMock()
    call_import_id = uuid4()
    source_row = MagicMock(call_import_id=call_import_id)
    expected = MagicMock()
    catalog_db.query.return_value.filter.return_value.first.return_value = expected

    result = _load_call_import_for_eval_row(catalog_db, source_row)

    assert result is expected
    catalog_db.query.assert_called_once()


def test_try_dispatch_import_path_reuses_catalog_session_when_sharded():
    catalog_db = MagicMock()
    evaluation = MagicMock(
        status="running",
        workspace_id=uuid4(),
        organization_id=uuid4(),
        call_import_id=uuid4(),
    )
    eval_row = MagicMock(id=uuid4(), status="pending", celery_task_id=None)
    source_row = MagicMock(
        status=CallImportRowStatus.PENDING,
        recording_s3_key="",
        recording_url="https://example.com/rec",
        call_import_id=evaluation.call_import_id,
        row_index=3,
    )
    call_import = MagicMock(provider="twilio")
    shard_db = MagicMock()

    with patch(
        "app.workers.concurrency.eval_dispatch._attach_sharded_eval_dispatch_rows",
        return_value=(shard_db, eval_row, source_row, False),
    ), patch((
        "app.db_sharding.sessions.is_sharding_enabled",
        return_value=True,
    ), patch(
        "app.workers.concurrency.import_dispatch._peek_authenticated_import_credit",
        return_value=None,
    ), patch(
        "app.workers.concurrency.limits.acquire_eval_slot",
        return_value=False,
    ):
        outcome = _try_dispatch_single_row(
            db=catalog_db,
            evaluation=evaluation,
            eval_row=eval_row,
            source_row=source_row,
            call_import=call_import,
        )

    assert outcome == EvalDispatchOutcome("at_capacity")
    shard_db.close.assert_not_called()
    catalog_db.close.assert_not_called()
