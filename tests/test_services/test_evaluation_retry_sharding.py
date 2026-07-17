"""Evaluation retry persistence under row sharding."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.call_imports.bulk_ops import _persist_evaluation_retry_targets


def test_persist_evaluation_retry_targets_commits_per_shard():
    catalog_db = MagicMock()
    evaluation = MagicMock(call_import_id=uuid4())
    eval_row = MagicMock(
        id=uuid4(),
        celery_task_id=None,
        status="failed",
    )
    source_row = MagicMock(id=uuid4(), row_index=5)

    shard_db = MagicMock()
    bound_eval = MagicMock()
    bound_source = MagicMock()
    shard_db.query.return_value.filter.return_value.all.side_effect = [
        [bound_eval],
        [bound_source],
    ]
    factory = MagicMock(return_value=shard_db)

    with patch(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        return_value=True,
    ), patch(
        "app.db_sharding.row_ops.shard_id_for_row",
        return_value="shard-a",
    ), patch(
        "app.services.call_imports.bulk_ops.db_pool_manager"
    ) as manager, patch(
        "app.services.call_imports.bulk_ops._batch_revoke_celery_task_ids",
    ), patch(
        "app.api.v1.routes.call_import_evaluations._prepare_source_row_for_retry",
    ) as prepare, patch(
        "app.api.v1.routes.call_import_evaluations._reset_eval_row_for_retry",
    ) as reset:
        manager.router = MagicMock(shard_ids=["shard-a"])
        manager.shard_session_factory = factory

        _persist_evaluation_retry_targets(
            catalog_db,
            evaluation,
            [(eval_row, source_row)],
        )

    prepare.assert_called_once_with(bound_source, transcribe_overwrite=False)
    reset.assert_called_once()
    shard_db.commit.assert_called_once()
    shard_db.close.assert_called_once()
    catalog_db.commit.assert_not_called()


def test_persist_evaluation_retry_targets_uses_catalog_when_not_sharded():
    catalog_db = MagicMock()
    evaluation = MagicMock(call_import_id=uuid4())
    eval_row = MagicMock(id=uuid4(), celery_task_id=None, status="failed")
    source_row = MagicMock(id=uuid4(), row_index=1)

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
