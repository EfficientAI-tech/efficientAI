"""Sharding-specific tests for eval-chain import → diarize handoff."""

from unittest.mock import MagicMock
from uuid import uuid4

from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
)
from app.models.enums import CallImportRowStatus
from tests.test_workers.test_process_call_import_row import (
    _FakeExotelClient,
    _FakeS3,
    _NonClosingSession,
    _patch_dependencies,
    _seed,
)


def _seed_eval_chain(db_session, *, org, call_import, row, transcript_source="diarised"):
    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=call_import.workspace_id,
        name="Eval run",
        selected_metric_ids=[],
        status="running",
        total_rows=1,
        transcript_source=transcript_source,
        stt_provider="google" if transcript_source == "diarised" else None,
        stt_model="chirp" if transcript_source == "diarised" else None,
        diarisation_llm_provider="openai" if transcript_source == "diarised" else None,
        diarisation_llm_model="gpt-4o" if transcript_source == "diarised" else None,
    )
    db_session.add(evaluation)
    eval_row = CallImportEvaluationRow(
        id=uuid4(),
        evaluation_id=evaluation.id,
        call_import_row_id=row.id,
        workspace_id=call_import.workspace_id,
        status="pending",
        celery_task_id="stale-import-task-id",
    )
    db_session.add(eval_row)
    db_session.commit()
    return evaluation, eval_row


def test_eval_chain_loads_evaluation_from_catalog_session(
    db_session, monkeypatch
):
    """With sharding, evaluation headers must be read from catalog, not shard."""
    org, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    evaluation, eval_row = _seed_eval_chain(
        db_session, org=org, call_import=call_import, row=row
    )

    fake_client = _FakeExotelClient(audio=b"hello-audio", content_type="audio/mpeg")
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    catalog_session = _NonClosingSession(db_session)
    chain_calls = []

    def fake_locate_call_import_row(row_id):
        return db_session, catalog_session, row, "data-shard-01"

    def fake_enqueue(
        shard_db,
        *,
        evaluation,
        eval_row,
        source_row,
        slot_task_id,
        restricted_metric_ids=None,
        transcribe_overwrite=False,
    ):
        chain_calls.append(
            {
                "evaluation_id": evaluation.id,
                "eval_row_id": eval_row.id,
                "source_row_id": source_row.id,
                "slot_task_id": slot_task_id,
                "shard_db": shard_db,
            }
        )
        return True

    monkeypatch.setattr(
        "app.db_sharding.row_ops.locate_call_import_row",
        fake_locate_call_import_row,
    )
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.workers.tasks.process_call_import_row._rollup_parent_status",
        lambda _db, _call_import: None,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.eval_dispatch.enqueue_eval_chain_transcribe_after_import",
        fake_enqueue,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.limits.slot_registered_for_task",
        lambda _task_id: False,
    )

    result = task_module.process_call_import_row_task.run(
        str(row.id),
        _eval_slot_task_id="slot-task-abc",
        run_eval_row_id=str(eval_row.id),
    )

    assert result["status"] == "completed"
    assert len(chain_calls) == 1
    assert chain_calls[0]["evaluation_id"] == evaluation.id
    assert chain_calls[0]["eval_row_id"] == eval_row.id
    assert chain_calls[0]["slot_task_id"] == "slot-task-abc"
    assert chain_calls[0]["shard_db"] is db_session


def test_production_eval_chain_skips_transcribe_and_redispatches(
    db_session, monkeypatch
):
    """Production-transcript evals should import recordings then evaluate, not diarise."""
    org, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    row.transcript = "Agent: hello\nUser: hi"
    db_session.commit()
    evaluation, eval_row = _seed_eval_chain(
        db_session,
        org=org,
        call_import=call_import,
        row=row,
        transcript_source="production",
    )

    fake_client = _FakeExotelClient(audio=b"hello-audio", content_type="audio/mpeg")
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    chain_called = {"value": False}
    finish_mock = MagicMock()

    def fake_enqueue(*args, **kwargs):
        chain_called["value"] = True
        return True

    monkeypatch.setattr(
        "app.workers.concurrency.eval_dispatch.enqueue_eval_chain_transcribe_after_import",
        fake_enqueue,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.limits.slot_registered_for_task",
        lambda _task_id: True,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.fair_dispatch.finish_eval_work_and_redispatch",
        finish_mock,
    )
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.workers.tasks.process_call_import_row._rollup_parent_status",
        lambda _db, _call_import: None,
    )

    result = task_module.process_call_import_row_task.run(
        str(row.id),
        _eval_slot_task_id="slot-task-prod",
        run_eval_row_id=str(eval_row.id),
    )

    assert result["status"] == "completed"
    assert chain_called["value"] is False
    finish_mock.assert_called_once_with("slot-task-prod")


def test_eval_chain_cleanup_clears_stale_task_ids_and_redispatches(
    db_session, monkeypatch
):
    """When direct chain misses, clear celery_task_id so fair dispatch can resume."""
    org, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    _evaluation, eval_row = _seed_eval_chain(
        db_session, org=org, call_import=call_import, row=row
    )
    row_id = row.id
    eval_row_id = eval_row.id
    row.celery_task_id = "import-task-id"
    db_session.commit()

    fake_client = _FakeExotelClient(audio=b"hello-audio", content_type="audio/mpeg")
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    finish_mock = MagicMock()
    locate_calls = {"count": 0}

    class _CatalogWithoutEvalHeader(_NonClosingSession):
        def query(self, *entities):
            if entities and entities[0] is CallImportEvaluation:
                empty = MagicMock()
                empty.filter.return_value.first.return_value = None
                return empty
            return self._session.query(*entities)

    catalog_session = _CatalogWithoutEvalHeader(db_session)

    def fake_locate_call_import_row(_row_id):
        located_row = (
            db_session.query(CallImportRow).filter(CallImportRow.id == row_id).one()
        )
        return db_session, catalog_session, located_row, "data-shard-01"

    def fake_locate_call_import_evaluation_row(_eval_row_id):
        locate_calls["count"] += 1
        refreshed_eval_row = (
            db_session.query(CallImportEvaluationRow)
            .filter(CallImportEvaluationRow.id == eval_row_id)
            .one()
        )
        refreshed_source = (
            db_session.query(CallImportRow)
            .filter(CallImportRow.id == row_id)
            .one()
        )
        return db_session, db_session, refreshed_eval_row, refreshed_source, "legacy"

    chain_called = {"value": False}

    def fake_enqueue(*args, **kwargs):
        chain_called["value"] = True
        return True

    monkeypatch.setattr(
        "app.db_sharding.row_ops.locate_call_import_row",
        fake_locate_call_import_row,
    )
    monkeypatch.setattr(
        "app.db_sharding.row_ops.locate_call_import_evaluation_row",
        fake_locate_call_import_evaluation_row,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.eval_dispatch.enqueue_eval_chain_transcribe_after_import",
        fake_enqueue,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.limits.slot_registered_for_task",
        lambda _task_id: True,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.fair_dispatch.finish_eval_work_and_redispatch",
        finish_mock,
    )
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.workers.tasks.process_call_import_row._rollup_parent_status",
        lambda _db, _call_import: None,
    )

    result = task_module.process_call_import_row_task.run(
        str(row_id),
        _eval_slot_task_id="slot-task-abc",
        run_eval_row_id=str(eval_row_id),
    )

    assert result["status"] == "completed"
    assert chain_called["value"] is False
    assert locate_calls["count"] == 1
    eval_row_fresh = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.id == eval_row_id)
        .one()
    )
    row_fresh = db_session.query(CallImportRow).filter(CallImportRow.id == row_id).one()
    assert eval_row_fresh.celery_task_id is None
    assert row_fresh.celery_task_id is None
    assert row_fresh.status == CallImportRowStatus.COMPLETED
    finish_mock.assert_called_once_with("slot-task-abc")


def test_production_eval_chain_cleanup_runs_when_eval_slot_expired(
    db_session, monkeypatch
):
    """Production eval imports must clear stale task ids and redispatch even
    after the reserved eval slot TTL expires mid-flight."""
    org, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    row.transcript = "Agent: hello\nUser: hi"
    db_session.commit()
    evaluation, eval_row = _seed_eval_chain(
        db_session,
        org=org,
        call_import=call_import,
        row=row,
        transcript_source="production",
    )
    row.celery_task_id = "stale-import-task"
    eval_row.celery_task_id = "stale-eval-task"
    db_session.commit()

    fake_client = _FakeExotelClient(audio=b"hello-audio", content_type="audio/mpeg")
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    finish_mock = MagicMock()
    monkeypatch.setattr(task_module, "_rollup_parent_status", lambda _db, _ci: None)

    def fake_locate_call_import_evaluation_row(_eval_row_id):
        refreshed_eval_row = (
            db_session.query(CallImportEvaluationRow)
            .filter(CallImportEvaluationRow.id == eval_row.id)
            .one()
        )
        refreshed_source = (
            db_session.query(CallImportRow)
            .filter(CallImportRow.id == row.id)
            .one()
        )
        return db_session, db_session, refreshed_eval_row, refreshed_source, "legacy"

    monkeypatch.setattr(
        "app.db_sharding.row_ops.locate_call_import_evaluation_row",
        fake_locate_call_import_evaluation_row,
    )
    monkeypatch.setattr(
        "app.db_sharding.row_ops.commit_shard_row_session",
        lambda session: session.commit(),
    )
    monkeypatch.setattr(
        "app.db_sharding.row_ops.close_row_sessions",
        lambda *_a, **_kw: None,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.limits.slot_registered_for_task",
        lambda _task_id: False,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.fair_dispatch.finish_eval_work_and_redispatch",
        finish_mock,
    )
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        lambda: False,
    )

    result = task_module.process_call_import_row_task.run(
        str(row.id),
        _eval_slot_task_id="expired-slot-task",
        run_eval_row_id=str(eval_row.id),
    )

    assert result["status"] == "completed"
    eval_row_fresh = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.id == eval_row.id)
        .one()
    )
    row_fresh = db_session.query(CallImportRow).filter(CallImportRow.id == row.id).one()
    assert eval_row_fresh.celery_task_id is None
    assert row_fresh.celery_task_id is None
    assert row_fresh.status == CallImportRowStatus.COMPLETED
    finish_mock.assert_called_once_with("expired-slot-task")


def test_try_dispatch_single_row_skips_when_bulk_operation_active(
    db_session, monkeypatch
):
    from app.workers.concurrency.eval_dispatch import _try_dispatch_single_row

    org, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    evaluation, eval_row = _seed_eval_chain(
        db_session, org=org, call_import=call_import, row=row
    )

    monkeypatch.setattr(
        "app.services.call_imports.evaluation_bulk_op.get_evaluation_bulk_operation",
        lambda _evaluation_id: "abort",
    )
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: False,
    )

    outcome = _try_dispatch_single_row(
        db=db_session,
        evaluation=evaluation,
        eval_row=eval_row,
        source_row=row,
    )

    assert outcome.result == "skip"
