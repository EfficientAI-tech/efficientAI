"""Evaluation retry persistence under row sharding."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.models.database import CallImportEvaluationRow, CallImportRow
from app.services.call_imports.bulk_ops import _persist_evaluation_retry_targets


def test_persist_evaluation_retry_targets_commits_per_shard():
    catalog_db = MagicMock()
    evaluation = SimpleNamespace(call_import_id=uuid4())
    eval_row_id = uuid4()
    source_row_id = uuid4()
    eval_row = SimpleNamespace(
        id=eval_row_id,
        celery_task_id=None,
        status="failed",
    )
    source_row = SimpleNamespace(id=source_row_id, row_index=5)

    shard_db = MagicMock()

    def _query(model):
        query = MagicMock()
        if model is CallImportEvaluationRow:
            query.filter.return_value.all.return_value = [eval_row]
        elif model is CallImportRow:
            query.filter.return_value.all.return_value = [source_row]
        else:
            query.filter.return_value.all.return_value = []
        return query

    shard_db.query.side_effect = _query
    session_factory = MagicMock(return_value=shard_db)

    with patch(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        return_value=True,
    ), patch(
        "app.db_sharding.row_ops.shard_id_for_row",
        return_value="shard-a",
    ), patch(
        "app.db_sharding.pool_manager.db_pool_manager"
    ) as manager, patch(
        "app.services.call_imports.bulk_ops._batch_revoke_celery_task_ids",
    ), patch(
        "app.api.v1.routes.call_import_evaluations._prepare_source_row_for_retry",
    ) as prepare, patch(
        "app.api.v1.routes.call_import_evaluations._reset_eval_row_for_retry",
    ) as reset:
        manager.router = SimpleNamespace(shard_ids=["shard-a"])
        manager.shard_session_factory = MagicMock(return_value=session_factory)

        _persist_evaluation_retry_targets(
            catalog_db,
            evaluation,
            [(eval_row, source_row)],
        )

    prepare.assert_called_once_with(source_row, transcribe_overwrite=False)
    reset.assert_called_once()
    assert shard_db.commit.call_count == 1
    shard_db.close.assert_called_once()
    catalog_db.commit.assert_not_called()


def test_persist_evaluation_retry_targets_uses_catalog_when_not_sharded():
    catalog_db = MagicMock()
    evaluation = SimpleNamespace(call_import_id=uuid4())
    eval_row = SimpleNamespace(id=uuid4(), celery_task_id=None, status="failed")
    source_row = SimpleNamespace(id=uuid4(), row_index=1)

    with patch(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        return_value=False,
    ), patch(
        "app.services.call_imports.bulk_ops._batch_revoke_celery_task_ids",
    ), patch(
        "app.api.v1.routes.call_import_evaluations._prepare_source_row_for_retry",
    ), patch(
        "app.api.v1.routes.call_import_evaluations._reset_eval_row_for_retry",
    ):
        _persist_evaluation_retry_targets(
            catalog_db,
            evaluation,
            [(eval_row, source_row)],
        )

    catalog_db.commit.assert_called_once()
