"""Fair dispatch should pick up pending rows on partially-completed runs."""

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
from app.workers.concurrency import fair_dispatch


def _seed_partial_run_with_pending_retry(db_session):
    org = Organization(id=uuid4(), name="Fair Dispatch Org")
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
        provider="exotel",
        original_filename="batch.csv",
        status=CallImportStatus.COMPLETED,
        total_rows=3,
        completed_rows=3,
        failed_rows=0,
    )
    db_session.add(call_import)
    db_session.flush()

    source_rows = []
    for idx in range(3):
        row = CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org.id,
            row_index=idx,
            conversation_id=f"conv-{idx}",
            status=CallImportRowStatus.COMPLETED,
            recording_s3_key=f"s3://bucket/{idx}.wav",
            diarised_transcript="Agent: hi\nUser: hello",
            diarised_transcript_status="completed",
        )
        source_rows.append(row)
        db_session.add(row)

    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=ws.id,
        name="run",
        status="partial",
        total_rows=3,
        completed_rows=2,
        failed_rows=1,
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        stt_provider="openai",
        stt_model="whisper-1",
        diarisation_llm_provider="openai",
        diarisation_llm_model="gpt-4o-mini",
        transcribe_mode="stt_llm",
        transcript_source="diarised",
        selected_metric_ids=[str(uuid4())],
    )
    db_session.add(evaluation)

    statuses = ["completed", "failed", "pending"]
    for source_row, status in zip(source_rows, statuses):
        db_session.add(
            CallImportEvaluationRow(
                id=uuid4(),
                evaluation_id=evaluation.id,
                call_import_row_id=source_row.id,
                status=status,
            )
        )

    db_session.commit()
    return ws.id, evaluation.id


def test_workspaces_with_pending_rows_includes_partial_status(db_session):
    workspace_id, _evaluation_id = _seed_partial_run_with_pending_retry(db_session)

    workspaces = fair_dispatch._workspaces_with_pending_rows(db_session)

    assert workspace_id in workspaces


def test_evaluations_with_pending_rows_includes_partial_status(db_session):
    workspace_id, evaluation_id = _seed_partial_run_with_pending_retry(db_session)

    evaluations = fair_dispatch._evaluations_with_pending_rows(
        db_session, workspace_id
    )

    assert evaluation_id in evaluations


def test_needs_transcribe_after_failed_diarisation_without_transcript(db_session):
    """Failed diarisation without a transcript should be eligible for re-dispatch."""
    from types import SimpleNamespace

    from app.workers.concurrency.eval_dispatch import (
        _diarisation_in_flight,
        _needs_transcribe_for_eval,
    )

    evaluation = SimpleNamespace(
        stt_provider="openai",
        stt_model="whisper-1",
        diarisation_llm_provider="openai",
        diarisation_llm_model="gpt-4o-mini",
        transcribe_mode="stt_llm",
    )
    source_row = SimpleNamespace(
        recording_s3_key="s3://bucket/1.wav",
        diarised_transcript="",
        diarised_transcript_status="failed",
        celery_task_id=None,
    )

    assert _needs_transcribe_for_eval(
        evaluation,
        source_row,
        transcribe_overwrite=False,
    )
    assert not _diarisation_in_flight(source_row)


def test_needs_transcribe_skips_when_diarised_transcript_exists(db_session):
    """Rows that already have a diarised transcript should go straight to eval."""
    from types import SimpleNamespace

    from app.workers.concurrency.eval_dispatch import _needs_transcribe_for_eval

    evaluation = SimpleNamespace(
        stt_provider="openai",
        stt_model="whisper-1",
        diarisation_llm_provider="openai",
        diarisation_llm_model="gpt-4o-mini",
        transcribe_mode="stt_llm",
    )
    source_row = SimpleNamespace(
        recording_s3_key="s3://bucket/1.wav",
        diarised_transcript="agent: hello",
        diarised_transcript_status="failed",
        celery_task_id=None,
    )

    assert not _needs_transcribe_for_eval(
        evaluation,
        source_row,
        transcribe_overwrite=False,
    )
