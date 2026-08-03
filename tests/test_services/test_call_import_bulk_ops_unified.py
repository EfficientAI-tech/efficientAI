"""Tests for unified pipeline helpers in call_import bulk_ops."""

import sys
import types
from uuid import uuid4

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Organization,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.models.schemas import CallImportTranscribeRequest
from app.services.call_imports.bulk_ops import (
    _all_source_row_ids,
    _source_row_ids_for_evaluation,
    count_all_source_rows,
    execute_bulk_diarization,
    execute_call_import_materialization,
    materialize_and_enqueue_evaluation,
)


def _seed_import_with_rows(db_session, *, completed: int, pending: int):
    org = Organization(id=uuid4(), name="Bulk Ops Org")
    ws = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add_all([org, ws])
    db_session.flush()
    call_import = CallImport(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=ws.id,
        status=CallImportStatus.PROCESSING,
        total_rows=completed + pending,
    )
    db_session.add(call_import)
    db_session.flush()
    rows = []
    for i in range(completed):
        rows.append(
            CallImportRow(
                id=uuid4(),
                call_import_id=call_import.id,
                organization_id=org.id,
                row_index=i,
                conversation_id=f"conv-completed-{i}",
                status=CallImportRowStatus.COMPLETED,
                recording_s3_key=f"key-{i}.mp3",
            )
        )
    for j in range(pending):
        rows.append(
            CallImportRow(
                id=uuid4(),
                call_import_id=call_import.id,
                organization_id=org.id,
                row_index=completed + j,
                conversation_id=f"conv-pending-{j}",
                status=CallImportRowStatus.PENDING,
                recording_url=f"https://example.com/{j}.mp3",
            )
        )
    db_session.add_all(rows)
    db_session.commit()
    return call_import, rows


def test_all_source_row_ids_include_pending_and_completed(db_session):
    call_import, rows = _seed_import_with_rows(db_session, completed=2, pending=3)
    ids = _all_source_row_ids(db_session, call_import.id)
    assert len(ids) == 5
    assert count_all_source_rows(db_session, call_import.id) == 5
    assert set(ids) == {row.id for row in rows}


def test_materialization_skips_import_dispatch_by_default(monkeypatch, db_session):
    org = Organization(id=uuid4(), name="Mat Org")
    ws = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add_all([org, ws])
    db_session.flush()
    call_import = CallImport(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=ws.id,
        status=CallImportStatus.PROCESSING,
        total_rows=1,
    )
    db_session.add(call_import)
    db_session.flush()
    db_session.add(
        CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org.id,
            row_index=0,
            conversation_id="conv-pending-0",
            status=CallImportRowStatus.PENDING,
        )
    )
    db_session.commit()

    called = {"import_dispatch": False}

    def fake_enqueue(*_a, **_kw):
        called["import_dispatch"] = True

    monkeypatch.setattr(
        "app.api.v1.routes.call_imports._enqueue_row_tasks",
        fake_enqueue,
    )

    result = execute_call_import_materialization(
        db_session,
        call_import.id,
        org.id,
        ws.id,
        schedule_import_dispatch=False,
    )
    assert result["status"] == "already_materialized"
    assert called["import_dispatch"] is False

    called["import_dispatch"] = False
    execute_call_import_materialization(
        db_session,
        call_import.id,
        org.id,
        ws.id,
        schedule_import_dispatch=True,
    )
    assert called["import_dispatch"] is True


def test_bulk_diarization_stores_redis_params_before_pending_commit(
    monkeypatch,
    db_session,
):
    """Rows must not be visible to the fair dispatcher until params exist."""
    monkeypatch.setattr(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        lambda: False,
    )
    org = Organization(id=uuid4(), name="Diar Org")
    ws = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add_all([org, ws])
    db_session.flush()
    call_import = CallImport(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=ws.id,
        status=CallImportStatus.PROCESSING,
        total_rows=1,
    )
    db_session.add(call_import)
    db_session.flush()
    row = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        row_index=0,
        conversation_id="conv-0",
        status=CallImportRowStatus.COMPLETED,
        recording_s3_key="recordings/conv-0.mp3",
        diarised_transcript_status="idle",
    )
    db_session.add(row)
    db_session.commit()

    observed = {"pending_at_store": None}

    def fake_store(row_ids, _params):
        observed["pending_at_store"] = row.diarised_transcript_status
        return list(row_ids), []

    monkeypatch.setattr(
        "app.workers.concurrency.diarization_dispatch.store_row_diarization_params_batch",
        fake_store,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.fair_diarization_dispatch.schedule_fair_diarization_dispatch",
        lambda **_kw: None,
    )

    payload = CallImportTranscribeRequest(
        stt_provider="deepgram",
        stt_model="nova-2",
        diarization_llm_provider="openai",
        diarization_llm_model="gpt-4o-mini",
        only_missing=True,
    )
    result = execute_bulk_diarization(db_session, call_import, payload)

    assert result.queued == 1
    assert observed["pending_at_store"] != "pending"
    db_session.refresh(row)
    assert row.diarised_transcript_status == "pending"
    assert row.celery_task_id is None


def test_source_row_ids_for_production_evaluation_omit_empty_transcripts(
    db_session,
):
    org = Organization(id=uuid4(), name="Prod Mat Org")
    ws = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add_all([org, ws])
    db_session.flush()
    call_import = CallImport(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=ws.id,
        status=CallImportStatus.COMPLETED,
        total_rows=3,
    )
    db_session.add(call_import)
    db_session.flush()

    with_transcript = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        row_index=0,
        conversation_id="with-text",
        transcript="Agent: hello",
        status=CallImportRowStatus.COMPLETED,
    )
    whitespace_only = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        row_index=1,
        conversation_id="blank-text",
        transcript="   ",
        status=CallImportRowStatus.COMPLETED,
    )
    no_transcript = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        row_index=2,
        conversation_id="missing-text",
        transcript=None,
        status=CallImportRowStatus.PENDING,
        recording_url="https://example.com/audio.mp3",
    )
    db_session.add_all([with_transcript, whitespace_only, no_transcript])
    db_session.flush()

    production_eval = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=ws.id,
        selected_metric_ids=[],
        status="pending",
        total_rows=1,
        transcript_source="production",
    )
    diarised_eval = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=ws.id,
        selected_metric_ids=[],
        status="pending",
        total_rows=3,
        transcript_source="diarised",
    )

    production_ids = _source_row_ids_for_evaluation(db_session, production_eval)
    diarised_ids = _source_row_ids_for_evaluation(db_session, diarised_eval)

    assert production_ids == [with_transcript.id]
    assert set(diarised_ids) == {
        with_transcript.id,
        whitespace_only.id,
        no_transcript.id,
    }


def test_materialize_production_evaluation_only_creates_transcript_rows(
    monkeypatch,
    db_session,
):
    org = Organization(id=uuid4(), name="Prod Enqueue Org")
    ws = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add_all([org, ws])
    db_session.flush()
    call_import = CallImport(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=ws.id,
        status=CallImportStatus.COMPLETED,
        total_rows=2,
    )
    db_session.add(call_import)
    db_session.flush()

    row_with_text = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        row_index=0,
        conversation_id="with-text",
        transcript="Customer: hi",
        status=CallImportRowStatus.COMPLETED,
    )
    row_without_text = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        row_index=1,
        conversation_id="without-text",
        transcript="",
        status=CallImportRowStatus.COMPLETED,
    )
    db_session.add_all([row_with_text, row_without_text])
    db_session.flush()

    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=ws.id,
        selected_metric_ids=[],
        status="pending",
        total_rows=1,
        transcript_source="production",
    )
    db_session.add(evaluation)
    db_session.commit()

    monkeypatch.setitem(
        sys.modules,
        "app.api.v1.routes.call_import_evaluations",
        types.SimpleNamespace(
            _enqueue_eval_rows_with_optional_transcribe=lambda *_a, **_kw: None,
        ),
    )

    materialize_and_enqueue_evaluation(db_session, evaluation.id)

    db_session.refresh(evaluation)
    eval_rows = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == evaluation.id)
        .all()
    )

    assert evaluation.total_rows == 1
    assert len(eval_rows) == 1
    assert eval_rows[0].call_import_row_id == row_with_text.id
