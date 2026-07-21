"""Tests for unified pipeline helpers in call_import bulk_ops."""

from uuid import uuid4

from app.models.database import CallImport, CallImportRow, Organization, Workspace
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.models.schemas import CallImportTranscribeRequest
from app.services.call_imports.bulk_ops import (
    _all_source_row_ids,
    count_all_source_rows,
    execute_bulk_diarization,
    execute_call_import_materialization,
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
