"""Paged user-insights generation with durable batch checkpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.db_sharding.scatter_gather import (
    EVALUATION_ANALYSIS_BATCH_SIZE,
    EvaluationRowPageCursor,
    count_completed_evaluation_row_pairs,
    evaluation_row_page_cursor_from_pair,
    load_completed_evaluation_row_pairs_page,
)
from app.models.database import CallImportEvaluation, CallImportEvaluationRow, CallImportRow, Metric
from app.models.schemas import EvaluationUserInsightsState
from app.services.call_import_user_insights import (
    SYNTHESIS_CALLS,
    build_row_payload,
    run_extraction_batch,
    run_synthesis,
    user_insights_state_to_db,
    _format_aggregate_summary,
    _aggregate_themes,
)
from app.services.evaluation_analysis_checkpoints import (
    JOB_KIND_USER_INSIGHTS,
    USER_INSIGHTS_CANCELLED_BY_USER_ERROR,
    batch_count_for_rows,
    completed_rows_from_batches,
    cursor_from_header,
    cursor_to_dict,
    init_job_header,
    list_analysis_batches,
    merge_extractions_from_batches,
    merge_theme_counts_from_batches,
    normalize_transcript_source,
    progress_header,
    upsert_analysis_batch,
    user_insights_raw_is_cancelled,
    new_job_run_id,
)

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[Dict[str, Any]], None]

EXTRACTION_SUB_BATCH_ROWS = 25


def pick_transcript_for_source(
    evaluation: CallImportEvaluation,
    source_row: CallImportRow,
    transcript_source: str,
) -> str:
    from app.services.call_import_user_insights import ROW_TRANSCRIPT_CHAR_CAP, _pick_transcript

    source = normalize_transcript_source(transcript_source)
    if source == "production":
        text = (source_row.transcript or "").strip()
    else:
        text = (source_row.diarised_transcript or "").strip()
        if not text:
            text = _pick_transcript(evaluation, source_row)
    return text[:ROW_TRANSCRIPT_CHAR_CAP]


def build_row_payload_for_source(
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
    metric_names: Dict[str, str],
    transcript_source: str,
) -> Dict[str, Any]:
    payload = build_row_payload(evaluation, eval_row, source_row, metric_names)
    transcript = pick_transcript_for_source(evaluation, source_row, transcript_source)
    payload["transcript"] = transcript
    return payload


def _sub_batch_payloads(
    rows: Sequence[Dict[str, Any]],
    *,
    size: int = EXTRACTION_SUB_BATCH_ROWS,
) -> List[List[Dict[str, Any]]]:
    chunk = max(1, size)
    return [list(rows[i : i + chunk]) for i in range(0, len(rows), chunk)]


def merge_theme_counts_into_header(
    header: Dict[str, Any],
    theme_delta: Dict[str, int],
) -> Dict[str, int]:
    existing = header.get("theme_counts")
    merged: Dict[str, int] = dict(existing) if isinstance(existing, dict) else {}
    for label, count in theme_delta.items():
        merged[label] = merged.get(label, 0) + int(count)
    header["theme_counts"] = merged
    return merged


def _cancelled_state(
    evaluation: CallImportEvaluation,
    raw: Dict[str, Any],
    *,
    llm_calls_used: int = 0,
) -> EvaluationUserInsightsState:
    progress_raw = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
    return EvaluationUserInsightsState(
        status="cancelled",
        insights=[],
        overview=None,
        generated_at=datetime.now(timezone.utc),
        generated_at_completed_rows=evaluation.completed_rows,
        progress=progress_raw,
        provider=raw.get("provider") if isinstance(raw.get("provider"), str) else None,
        model=raw.get("model") if isinstance(raw.get("model"), str) else None,
        llm_calls_used=llm_calls_used,
        max_llm_calls=None,
        error_message=USER_INSIGHTS_CANCELLED_BY_USER_ERROR,
        is_stale=False,
    )


def _finalize_synthesis(
    db: Session,
    evaluation: CallImportEvaluation,
    organization_id: UUID,
    provider,
    model: str,
    *,
    job_run_id: UUID,
    aggregate: Sequence[Any],
    raw_header: Dict[str, Any],
    on_progress: Optional[ProgressCallback] = None,
    is_cancelled: Optional[CancelCheck] = None,
) -> EvaluationUserInsightsState:
    if is_cancelled and is_cancelled():
        return _cancelled_state(
            evaluation,
            raw_header,
            llm_calls_used=int(raw_header.get("llm_calls_used") or 0),
        )

    batches = list_analysis_batches(
        db,
        evaluation_id=evaluation.id,
        job_kind=JOB_KIND_USER_INSIGHTS,
        job_run_id=job_run_id,
    )
    theme_counts = merge_theme_counts_from_batches(batches)
    if not theme_counts and isinstance(raw_header.get("theme_counts"), dict):
        theme_counts = {
            str(k): int(v)
            for k, v in raw_header["theme_counts"].items()
            if str(k).strip()
        }

    sample_quotes = merge_extractions_from_batches(batches)
    aggregate_summary = _format_aggregate_summary(aggregate)
    total_sampled = completed_rows_from_batches(batches)

    progress = raw_header.get("progress") if isinstance(raw_header.get("progress"), dict) else {}
    completed_calls = int(raw_header.get("llm_calls_used") or 0)

    try:
        insights, overview = run_synthesis(
            db,
            organization_id,
            provider,
            model,
            theme_counts=theme_counts,
            sample_quotes=sample_quotes,
            aggregate_summary=aggregate_summary,
            total_sampled_rows=max(total_sampled, 1),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "User insights synthesis failed for evaluation {}: {}",
            evaluation.id,
            exc,
        )
        return EvaluationUserInsightsState(
            status="failed",
            error_message=f"Synthesis failed: {exc}",
            generated_at=datetime.now(timezone.utc),
            llm_calls_used=completed_calls,
            progress=progress,
            provider=provider.value if hasattr(provider, "value") else str(provider),
            model=model,
        )

    completed_calls += SYNTHESIS_CALLS
    if on_progress:
        on_progress(
            {
                **progress,
                "phase": "completed",
                "completed_llm_calls": completed_calls,
            }
        )

    if not insights:
        return EvaluationUserInsightsState(
            status="failed",
            error_message="LLM returned no insight blocks.",
            generated_at=datetime.now(timezone.utc),
            llm_calls_used=completed_calls,
            progress=progress,
            provider=provider.value if hasattr(provider, "value") else str(provider),
            model=model,
        )

    return EvaluationUserInsightsState(
        status="completed",
        insights=insights,
        overview=overview,
        generated_at=datetime.now(timezone.utc),
        generated_at_completed_rows=evaluation.completed_rows,
        progress={
            **progress,
            "phase": "completed",
            "completed_llm_calls": completed_calls,
        },
        provider=provider.value if hasattr(provider, "value") else str(provider),
        model=model,
        llm_calls_used=completed_calls,
        is_stale=False,
    )


def process_user_insights_wave_step(
    db: Session,
    evaluation: CallImportEvaluation,
    organization_id: UUID,
    provider,
    model: str,
    *,
    metrics: Sequence[Metric],
    aggregate: Sequence[Any],
    transcript_source: str,
    job_run_id: UUID,
    on_progress: Optional[ProgressCallback] = None,
    is_cancelled: Optional[CancelCheck] = None,
) -> Tuple[str, Optional[EvaluationUserInsightsState]]:
    """Run one wave step. Returns ``(next_action, state_if_terminal)``.

    ``next_action`` is ``continue`` (caller should re-enqueue), ``done``, or ``idle``.
    """
    from app.services.call_import_user_insights import _metric_name_map

    raw = evaluation.user_insights if isinstance(evaluation.user_insights, dict) else {}
    if user_insights_raw_is_cancelled(raw):
        return "idle", _cancelled_state(evaluation, raw)

    progress = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
    phase = str(progress.get("phase") or "rows")
    total_rows = int(progress.get("total_rows") or 0)
    total_batches = int(progress.get("total_batches") or 0)
    completed_batches = int(progress.get("completed_batches") or 0)
    llm_calls_used = int(raw.get("llm_calls_used") or 0)

    if phase == "synthesis" or (
        total_batches > 0 and completed_batches >= total_batches
    ):
        state = _finalize_synthesis(
            db,
            evaluation,
            organization_id,
            provider,
            model,
            job_run_id=job_run_id,
            aggregate=aggregate,
            raw_header=raw,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        return "done", state

    cursor = cursor_from_header(raw)
    pairs = load_completed_evaluation_row_pairs_page(
        db,
        evaluation.id,
        limit=EVALUATION_ANALYSIS_BATCH_SIZE,
        after_cursor=cursor,
    )
    if not pairs:
        if completed_batches == 0:
            return "done", EvaluationUserInsightsState(
                status="failed",
                error_message="No completed rows with metric scores to analyze.",
                generated_at=datetime.now(timezone.utc),
            )
        raw["progress"] = {**progress, "phase": "synthesis"}
        evaluation.user_insights = raw
        state = _finalize_synthesis(
            db,
            evaluation,
            organization_id,
            provider,
            model,
            job_run_id=job_run_id,
            aggregate=aggregate,
            raw_header=raw,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        return "done", state

    metric_names = _metric_name_map(metrics)
    row_payloads: List[Dict[str, Any]] = []
    skipped = 0
    for eval_row, source_row in pairs:
        if eval_row.status != "completed":
            continue
        payload = build_row_payload_for_source(
            evaluation,
            eval_row,
            source_row,
            metric_names,
            transcript_source,
        )
        if not (payload.get("transcript") or "").strip():
            skipped += 1
            continue
        row_payloads.append(payload)

    batch_index = completed_batches
    batch_extractions: List[Dict[str, Any]] = []
    batch_theme: Dict[str, int] = {}

    for sub_batch in _sub_batch_payloads(row_payloads):
        if is_cancelled and is_cancelled():
            return "idle", _cancelled_state(
                evaluation, raw, llm_calls_used=llm_calls_used
            )
        try:
            extracted = run_extraction_batch(
                db, organization_id, provider, model, sub_batch
            )
            batch_extractions.extend(extracted)
            batch_theme = _aggregate_themes(batch_extractions)
            upsert_analysis_batch(
                db,
                evaluation_id=evaluation.id,
                job_kind=JOB_KIND_USER_INSIGHTS,
                job_run_id=job_run_id,
                batch_index=batch_index,
                payload={
                    "extractions": batch_extractions,
                    "theme_counts": batch_theme,
                    "rows_processed": len(row_payloads),
                    "rows_skipped_empty_transcript": skipped,
                },
                transcript_source=transcript_source,
                status="in_progress",
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "User insights extraction sub-batch failed for evaluation {}: {}",
                evaluation.id,
                exc,
            )
        llm_calls_used += 1

    last_pair = pairs[-1]
    page_cursor = evaluation_row_page_cursor_from_pair(last_pair)
    merge_theme_counts_into_header(raw, _aggregate_themes(batch_extractions))

    upsert_analysis_batch(
        db,
        evaluation_id=evaluation.id,
        job_kind=JOB_KIND_USER_INSIGHTS,
        job_run_id=job_run_id,
        batch_index=batch_index,
        payload={
            "extractions": batch_extractions,
            "theme_counts": batch_theme,
            "rows_processed": len(row_payloads),
            "rows_skipped_empty_transcript": skipped,
        },
        cursor=page_cursor,
        transcript_source=transcript_source,
        status="completed",
    )

    completed_batches += 1
    completed_rows = int(progress.get("completed_rows") or 0) + len(pairs)
    new_progress = progress_header(
        completed_rows=completed_rows,
        total_rows=total_rows,
        completed_batches=completed_batches,
        total_batches=total_batches,
        completed_llm_calls=llm_calls_used,
        total_llm_calls=int(progress.get("total_llm_calls") or 0),
        phase="rows" if completed_batches < total_batches else "synthesis",
    )
    raw["progress"] = new_progress
    raw["cursor"] = cursor_to_dict(page_cursor)
    raw["llm_calls_used"] = llm_calls_used
    evaluation.user_insights = raw

    if on_progress:
        on_progress(new_progress)

    if completed_batches >= total_batches:
        return "continue", None
    return "continue", None


def start_user_insights_job_header(
    evaluation: CallImportEvaluation,
    db: Session,
    *,
    job_run_id: UUID,
    transcript_source: str,
    provider: Optional[str],
    model: Optional[str],
    prior_insights: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    total_rows = count_completed_evaluation_row_pairs(db, evaluation.id)
    total_batches = batch_count_for_rows(total_rows)
    header = init_job_header(
        job_run_id=job_run_id,
        transcript_source=normalize_transcript_source(transcript_source),
        total_rows=total_rows,
        total_batches=total_batches,
        provider=provider,
        model=model,
        extra={
            "insights": prior_insights or [],
            "generated_at_completed_rows": evaluation.completed_rows,
            "llm_calls_used": 0,
            "theme_counts": {},
            "cursor": None,
        },
    )
    header["progress"]["total_llm_calls"] = 0
    return header
