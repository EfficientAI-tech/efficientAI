"""Deferred Flexprice metering for call-import evaluation workers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
)


def enqueue_recording_minutes_for_completed_row(
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    *,
    audio_seconds: int,
    billable_minutes: int,
) -> None:
    if billable_minutes <= 0:
        return
    from app.services.billing.flexprice_service import (
        buffer_call_import_recording_minutes_billed,
    )

    buffer_call_import_recording_minutes_billed(
        evaluation.organization_id,
        eval_row.id,
        workspace_id=eval_row.workspace_id or evaluation.workspace_id,
        evaluation_id=evaluation.id,
        call_import_id=evaluation.call_import_id,
        audio_seconds=audio_seconds,
        billable_minutes=billable_minutes,
    )


def maybe_enqueue_recording_minutes_for_completed_row(
    db: Session,
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    *,
    source_row: CallImportRow | None = None,
    resolve_audio_seconds,
    billable_minutes_fn,
) -> None:
    if (eval_row.status or "").lower() != "completed":
        return
    if source_row is None:
        source_row = (
            db.query(CallImportRow)
            .filter(CallImportRow.id == eval_row.call_import_row_id)
            .first()
        )
    if source_row is None:
        return
    if not (source_row.recording_s3_key or "").strip():
        return

    audio_seconds = resolve_audio_seconds(db, eval_row, source_row)
    minutes = billable_minutes_fn(audio_seconds)
    enqueue_recording_minutes_for_completed_row(
        evaluation,
        eval_row,
        audio_seconds=audio_seconds,
        billable_minutes=minutes,
    )


def buffer_call_import_evaluation_pass(
    evaluation: CallImportEvaluation,
    *,
    rows_billed: int,
    completed_total: int,
) -> bool:
    if rows_billed <= 0:
        return False
    from app.services.billing.flexprice_service import (
        buffer_call_import_evaluation_completed,
    )

    metric_count = len(evaluation.selected_metric_ids or [])
    return buffer_call_import_evaluation_completed(
        evaluation.organization_id,
        evaluation.id,
        workspace_id=evaluation.workspace_id,
        call_import_id=evaluation.call_import_id,
        rows_billed=rows_billed,
        completed_total=completed_total,
        total_rows=int(evaluation.total_rows or 0),
        metric_count=metric_count,
    )
