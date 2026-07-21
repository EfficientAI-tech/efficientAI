"""Regression tests for eval-chain diarisation cleanup parent rollup."""

from __future__ import annotations

from app.workers.tasks.evaluate_call_import_row_core import (
    _apply_parent_status_from_counters,
    reconcile_evaluation_counters,
    rollup_parent,
)
from app.workers.tasks.transcribe_call_import_row import (
    _apply_eval_chain_transcribe_cleanup,
)
from tests.test_workers.test_evaluate_call_import_row import (
    _patch_row_location,
    _seed,
)


def test_eval_chain_transcribe_cleanup_rollup_partial_after_retry(
    db_session,
    monkeypatch,
):
    """Diarisation failures during retry must roll up parent counters to partial."""
    _patch_row_location(monkeypatch, db_session)

    _, _, _, source_rows, evaluation, eval_rows = _seed(db_session, row_count=4)

    eval_rows[0].status = "completed"
    eval_rows[1].status = "completed"
    eval_rows[2].status = "failed"
    eval_rows[3].status = "failed"
    evaluation.status = "partial"
    evaluation.completed_rows = 2
    evaluation.failed_rows = 2
    db_session.commit()

    for row in (eval_rows[2], eval_rows[3]):
        row.status = "pending"
        row.error_message = None
        row.finished_at = None
    db_session.flush()
    reconcile_evaluation_counters(db_session, evaluation)
    _apply_parent_status_from_counters(evaluation)
    db_session.commit()

    assert evaluation.status == "running"
    assert evaluation.completed_rows == 2
    assert evaluation.failed_rows == 0

    eval_rows[2].status = "completed"
    rollup_parent(
        db_session,
        evaluation,
        previous_row_status="pending",
        new_row_status="completed",
    )
    db_session.commit()
    db_session.refresh(evaluation)

    assert evaluation.completed_rows == 3
    assert evaluation.failed_rows == 0
    assert evaluation.status == "running"

    source_rows[3].diarised_transcript_status = "failed"
    source_rows[3].diarised_transcript_error = "STT timeout"
    eval_rows[3].status = "pending"
    db_session.commit()

    _apply_eval_chain_transcribe_cleanup(str(eval_rows[3].id))

    db_session.refresh(evaluation)
    db_session.refresh(eval_rows[3])

    assert eval_rows[3].status == "failed"
    assert evaluation.completed_rows == 3
    assert evaluation.failed_rows == 1
    assert evaluation.status == "partial"


def test_fail_eval_row_for_import_rollup(db_session, monkeypatch):
    """Import fetch failures during eval dispatch must roll up parent counters."""
    from app.models.enums import CallImportRowStatus
    from app.workers.concurrency.eval_dispatch import _fail_eval_row_for_import

    _patch_row_location(monkeypatch, db_session)

    _, _, _, source_rows, evaluation, eval_rows = _seed(db_session, row_count=2)
    eval_rows[0].status = "completed"
    evaluation.status = "running"
    evaluation.completed_rows = 1
    evaluation.failed_rows = 0
    source_rows[1].status = CallImportRowStatus.FAILED
    source_rows[1].recording_s3_key = None
    source_rows[1].error_message = "Recording fetch failed"
    db_session.commit()

    _fail_eval_row_for_import(
        db_session,
        eval_rows[1],
        source_rows[1],
        catalog_db=db_session,
        evaluation=evaluation,
    )

    db_session.refresh(evaluation)
    db_session.refresh(eval_rows[1])

    assert eval_rows[1].status == "failed"
    assert evaluation.completed_rows == 1
    assert evaluation.failed_rows == 1
    assert evaluation.status == "partial"
