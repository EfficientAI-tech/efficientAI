"""Eval-chain import failure handling."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    Organization,
    TelephonyIntegration,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus, TelephonyProvider
from app.workers.concurrency.eval_dispatch import (
    _try_dispatch_single_row,
    recover_eval_row_for_eval_chain,
    source_row_import_blocks_eval,
)


def _seed_eval_row(db_session):
    org = Organization(id=uuid4(), name="Eval Import Org")
    db_session.add(org)
    workspace = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add(workspace)
    integration = TelephonyIntegration(
        organization_id=org.id,
        provider=TelephonyProvider.EXOTEL.value,
        auth_id="enc",
        auth_token="enc",
        voice_app_id="sid",
        is_active=True,
    )
    db_session.add(integration)
    db_session.flush()

    metric = Metric(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=workspace.id,
        name="Quality",
        metric_type="rating",
        trigger="always",
        enabled=True,
        supported_surfaces=["agent"],
        enabled_surfaces=["agent"],
    )
    db_session.add(metric)

    call_import = CallImport(
        organization_id=org.id,
        workspace_id=workspace.id,
        provider=TelephonyProvider.EXOTEL.value,
        telephony_integration_id=integration.id,
        original_filename="batch.csv",
        total_rows=1,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.PROCESSING,
    )
    db_session.add(call_import)
    db_session.flush()

    source_row = CallImportRow(
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=workspace.id,
        row_index=0,
        conversation_id="call-0",
        recording_url="https://api.exotel.com/recordings/0.mp3",
        transcript="hello",
        status=CallImportRowStatus.FAILED,
        error_message="recording URL: old failure",
        recording_s3_key="audio/org/test.mp3",
        diarised_transcript="Agent: hi\nUser: hello",
        diarised_transcript_status="completed",
    )
    db_session.add(source_row)
    db_session.flush()

    evaluation = CallImportEvaluation(
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=workspace.id,
        name="Run",
        selected_metric_ids=[str(metric.id)],
        status="running",
        total_rows=1,
        completed_rows=0,
        failed_rows=0,
        llm_provider="openai",
        llm_model="gpt-4o",
    )
    db_session.add(evaluation)
    db_session.flush()

    eval_row = CallImportEvaluationRow(
        evaluation_id=evaluation.id,
        call_import_row_id=source_row.id,
        status="pending",
    )
    db_session.add(eval_row)
    db_session.commit()
    return call_import, evaluation, eval_row, source_row


def test_source_row_import_blocks_eval_false_when_audio_present(db_session):
    _, _, _, source_row = _seed_eval_row(db_session)
    assert source_row_import_blocks_eval(source_row) is False


def test_source_row_import_blocks_eval_true_when_failed_without_audio(db_session):
    _, _, _, source_row = _seed_eval_row(db_session)
    source_row.recording_s3_key = None
    source_row.status = CallImportRowStatus.FAILED
    assert source_row_import_blocks_eval(source_row) is True


def test_dispatch_does_not_fail_eval_when_source_failed_but_audio_present(
    db_session, monkeypatch
):
    call_import, evaluation, eval_row, source_row = _seed_eval_row(db_session)

    monkeypatch.setattr(
        "app.services.call_imports.evaluation_bulk_op.get_evaluation_bulk_operation",
        lambda _evaluation_id: None,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.eval_dispatch.acquire_eval_slot",
        lambda **_kwargs: False,
    )

    outcome = _try_dispatch_single_row(
        db=db_session,
        evaluation=evaluation,
        eval_row=eval_row,
        source_row=source_row,
        call_import=call_import,
    )

    db_session.refresh(eval_row)
    assert eval_row.status == "pending"
    assert eval_row.error_message is None
    assert outcome.result in {"at_capacity", "dispatched", "skip"}


def test_recover_eval_row_for_eval_chain_clears_stale_import_failure(db_session):
    _, _, eval_row, _ = _seed_eval_row(db_session)
    eval_row.status = "failed"
    eval_row.error_message = "Transient: Telephony credential throttled for 15s"
    db_session.commit()

    recover_eval_row_for_eval_chain(eval_row)

    assert eval_row.status == "pending"
    assert eval_row.error_message is None
    assert eval_row.finished_at is None


def test_recover_eval_row_for_eval_chain_preserves_user_abort(db_session):
    _, _, eval_row, _ = _seed_eval_row(db_session)
    eval_row.status = "failed"
    eval_row.error_message = "Evaluation cancelled by user"
    eval_row.finished_at = datetime.now(timezone.utc)
    db_session.commit()

    recover_eval_row_for_eval_chain(eval_row)

    assert eval_row.status == "failed"
    assert eval_row.error_message == "Evaluation cancelled by user"
    assert eval_row.finished_at is not None
