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

    prepare.assert_not_called()
    reset.assert_not_called()
    shard_db.execute.assert_called()
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


def _compiled_sql(query) -> str:
    from sqlalchemy.dialects import postgresql

    return " ".join(
        str(query.statement.compile(dialect=postgresql.dialect())).lower().split()
    )


def _assert_transcript_bodies_not_selected(sql: str) -> None:
    stripped = sql
    for column in ("transcript", "diarised_transcript"):
        stripped = stripped.replace(
            f"length(trim(coalesce(call_import_rows.{column},",
            "",
        )
    stripped = stripped.replace("diarised_transcript_status", "")
    stripped = stripped.replace("diarised_transcript_error", "")
    assert "transcript" not in stripped


def test_retry_target_query_filters_status_and_skips_transcript_bodies():
    from sqlalchemy.orm import Session

    from app.db_sharding.eval_rows import (
        retry_eval_page_query,
        retry_source_page_query,
    )
    from app.services.call_imports.bulk_ops import (
        import_failed_retry_query,
        import_stuck_pending_retry_query,
    )

    session = Session()
    failed_sql = _compiled_sql(
        retry_eval_page_query(
            session,
            uuid4(),
            status="failed",
            include_metric_scores=False,
            ordered=False,
        )
    )
    assert "status" in failed_sql
    assert "order by" not in failed_sql
    assert "metric_scores" not in failed_sql
    assert "call_import_rows" not in failed_sql

    subset_sql = _compiled_sql(
        retry_eval_page_query(
            session,
            uuid4(),
            status="completed",
            include_metric_scores=True,
            ordered=False,
        )
    )
    assert "metric_scores" in subset_sql
    assert "order by" not in subset_sql
    assert "call_import_rows" not in subset_sql

    source_sql = _compiled_sql(retry_source_page_query(session, [uuid4()]))
    _assert_transcript_bodies_not_selected(source_sql)

    failed_import_sql = _compiled_sql(import_failed_retry_query(session, uuid4()))
    assert "status" in failed_import_sql
    assert "recording_s3_key" in failed_import_sql
    assert "order by" not in failed_import_sql
    _assert_transcript_bodies_not_selected(failed_import_sql)

    stuck_sql = _compiled_sql(import_stuck_pending_retry_query(session, uuid4()))
    assert "attempts" in stuck_sql
    assert "order by" not in stuck_sql
    _assert_transcript_bodies_not_selected(stuck_sql)


def test_metric_retry_page_is_one_postgres_update():
    keep = uuid4()
    drop = uuid4()
    eval_row = SimpleNamespace(
        id=uuid4(),
        celery_task_id=None,
        metric_scores={
            str(keep): {"value": 2},
            str(drop): {"value": 1},
        },
    )
    source_row = SimpleNamespace(
        id=uuid4(),
        status="completed",
        celery_task_id=None,
        recording_s3_key="audio/already-there.wav",
        error_message=None,
        attempts=0,
        diarised_transcript=None,
        diarised_transcript_status="completed",
        diarised_transcript_error=None,
    )
    session = MagicMock()
    session.get_bind.return_value.dialect.name = "postgresql"

    from app.services.call_imports.bulk_ops import _write_retry_page

    _write_retry_page(
        session,
        [(eval_row, source_row)],
        metric_ids=[drop],
    )

    statement, params = session.execute.call_args[0]
    assert "unnest" in str(statement).lower()
    assert params["ids"] == [eval_row.id]
    assert str(drop) not in params["scores"][0]
    assert params["scores"][0][str(keep)]["value"] == 2
    session.commit.assert_called_once()


def test_clean_source_row_is_not_rewritten_on_retry():
    from app.api.v1.routes.call_import_evaluations import source_retry_assignments

    source_row = SimpleNamespace(
        status="completed",
        celery_task_id=None,
        recording_s3_key="audio/already-there.wav",
        error_message=None,
        attempts=0,
        diarised_transcript=None,
        diarised_transcript_status="completed",
        diarised_transcript_error=None,
    )
    assert source_retry_assignments(source_row, transcribe_overwrite=False) == {}


def test_failed_diarisation_without_text_is_one_shared_update():
    from app.api.v1.routes.call_import_evaluations import source_retry_assignments

    source_row = SimpleNamespace(
        status="completed",
        celery_task_id=None,
        recording_s3_key="audio/already-there.wav",
        error_message=None,
        attempts=0,
        diarised_transcript=None,
        diarised_transcript_status="failed",
        diarised_transcript_error="STT timeout",
    )
    assert source_retry_assignments(source_row, transcribe_overwrite=False) == {
        "diarised_transcript_status": "idle",
        "diarised_transcript_error": None,
    }


def test_explicit_retry_ids_are_loaded_in_pages():
    from app.db_sharding import eval_rows
    from app.services.call_imports.bulk_ops import execute_evaluation_retry

    evaluation_id = uuid4()
    requested = [uuid4(), uuid4(), uuid4()]
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=evaluation_id,
        call_import_id=uuid4(),
    )
    loaded = []

    def _load(_session, _evaluation_id, **kwargs):
        loaded.append(list(kwargs["row_ids"]))
        return []

    with patch.object(eval_rows, "RETRY_ROW_PAGE_SIZE", 2), patch(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        return_value=False,
    ), patch(
        "app.db_sharding.eval_rows.iter_evaluation_row_sessions",
        return_value=[(db, None)],
    ), patch(
        "app.db_sharding.eval_rows.load_retry_target_page",
        side_effect=_load,
    ), patch(
        "app.workers.concurrency.fair_dispatch.schedule_fair_dispatch",
    ):
        result = execute_evaluation_retry(
            db,
            evaluation_id,
            eval_row_ids=requested,
        )

    assert result["requeued"] == 0
    assert loaded == [requested[:2], requested[2:]]
    db.execute.assert_not_called()


def test_metric_page_is_not_reset_when_marker_write_fails():
    from app.services.call_imports.bulk_ops import execute_evaluation_retry

    evaluation_id = uuid4()
    metric_id = uuid4()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=evaluation_id,
        call_import_id=uuid4(),
    )
    eval_row = SimpleNamespace(
        id=uuid4(),
        celery_task_id=None,
        status="failed",
        metric_scores={str(metric_id): {"value": 1}},
    )
    source_row = SimpleNamespace(id=uuid4(), status="completed")

    with patch(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        return_value=False,
    ), patch(
        "app.db_sharding.eval_rows.iter_evaluation_row_sessions",
        return_value=[(db, None)],
    ), patch(
        "app.db_sharding.eval_rows.load_retry_target_page",
        side_effect=[[(eval_row, source_row)], []],
    ), patch(
        "app.workers.concurrency.fair_dispatch.store_rows_restricted_metrics",
        return_value=False,
    ), patch(
        "app.workers.concurrency.fair_dispatch.schedule_fair_dispatch",
    ) as schedule:
        try:
            execute_evaluation_retry(
                db,
                evaluation_id,
                metric_ids=[metric_id],
            )
        except RuntimeError as exc:
            assert "leaving the page unchanged" in str(exc)
        else:
            raise AssertionError("retry should stop when markers are not stored")

    db.execute.assert_not_called()
    schedule.assert_not_called()
