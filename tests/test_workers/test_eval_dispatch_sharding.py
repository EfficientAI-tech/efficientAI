"""Sharding commit paths for eval dispatch must bypass catalog-only FK parents."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
)


def _make_eval_bundle(*, transcript_source: str = "diarised"):
    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        name="Eval",
        selected_metric_ids=[],
        status="running",
        transcript_source=transcript_source,
        stt_provider="google",
        stt_model="chirp",
        diarisation_llm_provider="openai",
        diarisation_llm_model="gpt-4o",
    )
    source_row = CallImportRow(
        id=uuid4(),
        call_import_id=evaluation.call_import_id,
        organization_id=evaluation.organization_id,
        workspace_id=evaluation.workspace_id,
        row_index=0,
        conversation_id="c1",
        recording_url="https://example.com/a.mp3",
        recording_s3_key="audio/a.mp3",
        status="completed",
    )
    eval_row = CallImportEvaluationRow(
        id=uuid4(),
        evaluation_id=evaluation.id,
        call_import_row_id=source_row.id,
        workspace_id=evaluation.workspace_id,
        status="pending",
        celery_task_id="old-task",
    )
    return evaluation, eval_row, source_row


@patch("app.workers.concurrency.eval_dispatch.build_eval_chain_transcribe_apply_async")
@patch("app.db_sharding.row_ops.shard_row_write_context")
def test_enqueue_eval_chain_uses_shard_write_context(mock_context, mock_build_async):
    from app.workers.concurrency.eval_dispatch import (
        enqueue_eval_chain_transcribe_after_import,
    )

    evaluation, eval_row, source_row = _make_eval_bundle()
    db = MagicMock()
    mock_build_async.return_value = MagicMock(id="transcribe-task-id")
    mock_context.return_value.__enter__ = MagicMock(return_value=None)
    mock_context.return_value.__exit__ = MagicMock(return_value=False)

    result = enqueue_eval_chain_transcribe_after_import(
        db,
        evaluation=evaluation,
        eval_row=eval_row,
        source_row=source_row,
        slot_task_id="slot-task-id",
    )

    assert result is True
    mock_context.assert_called_once_with(db)
    db.flush.assert_called_once()
    db.commit.assert_called_once()
    assert eval_row.celery_task_id == "transcribe-task-id"
    assert source_row.celery_task_id == "slot-task-id"


@patch("app.workers.concurrency.eval_dispatch.build_eval_chain_transcribe_apply_async")
@patch("app.db_sharding.row_ops.shard_row_write_context")
def test_enqueue_eval_chain_skips_transcribe_for_production_source(
    mock_context, mock_build_async
):
    from app.workers.concurrency.eval_dispatch import (
        enqueue_eval_chain_transcribe_after_import,
    )

    evaluation, eval_row, source_row = _make_eval_bundle(transcript_source="production")
    db = MagicMock()

    result = enqueue_eval_chain_transcribe_after_import(
        db,
        evaluation=evaluation,
        eval_row=eval_row,
        source_row=source_row,
        slot_task_id="slot-task-id",
    )

    assert result is False
    mock_context.assert_not_called()
    mock_build_async.assert_not_called()


@patch("app.workers.concurrency.eval_dispatch.acquire_eval_slot", return_value=True)
@patch("app.db_sharding.row_ops.shard_row_write_context")
def test_reserve_slot_and_enqueue_uses_shard_write_context(
    mock_context, _mock_acquire
):
    from app.workers.concurrency.eval_dispatch import _reserve_slot_and_enqueue

    evaluation, eval_row, _source_row = _make_eval_bundle()
    db = MagicMock()
    mock_context.return_value.__enter__ = MagicMock(return_value=None)
    mock_context.return_value.__exit__ = MagicMock(return_value=False)

    def enqueue_fn(_task_id: str):
        return MagicMock(id="queued-task-id")

    assert (
        _reserve_slot_and_enqueue(
            evaluation=evaluation,
            eval_row=eval_row,
            db=db,
            enqueue_fn=enqueue_fn,
        )
        is True
    )
    mock_context.assert_called_once_with(db)
    db.commit.assert_called_once()
    assert eval_row.celery_task_id == "queued-task-id"
