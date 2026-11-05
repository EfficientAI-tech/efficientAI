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
    rows_completed_for_batches,
    upsert_analysis_batch,
    user_insights_raw_is_cancelled,
    new_job_run_id,
)

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[Dict[str, Any]], None]

EXTRACTION_SUB_BATCH_ROWS = 50
# Rows small enough to fit in a single extraction pass (with headroom for
# per-row transcript + metric rationale tokens).
EXTRACTION_SINGLE_PASS_MAX_ROWS = 40
# Checkpoint index used for the final synthesis payload (kept above any row
# page index so row batching can never collide with it).
SYNTHESIS_BATCH_INDEX_OFFSET = 100_000


def extraction_sub_batch_size(row_count: int) -> int:
    """Size each extraction LLM call; fewer round-trips for small evals."""
    if row_count <= 0:
        return EXTRACTION_SUB_BATCH_ROWS
    if row_count <= EXTRACTION_SINGLE_PASS_MAX_ROWS:
        return row_count
    return EXTRACTION_SUB_BATCH_ROWS


def extraction_pass_count(row_count: int) -> int:
    if row_count <= 0:
        return 0
    return (row_count + extraction_sub_batch_size(row_count) - 1) // extraction_sub_batch_size(
        row_count
    )


def estimate_user_insights_total_llm_calls(total_rows: int) -> int:
    """Extraction sub-passes across all row pages plus synthesis."""
    if total_rows <= 0:
        return 0
    total_batches = batch_count_for_rows(total_rows)
    extraction = 0
    remaining = total_rows
    for _ in range(total_batches):
        page_rows = min(EVALUATION_ANALYSIS_BATCH_SIZE, remaining)
        if page_rows <= 0:
            break
        extraction += extraction_pass_count(page_rows)
        remaining -= page_rows
    return extraction + SYNTHESIS_CALLS


def reconcile_user_insights_job_header(
    db: Session,
    evaluation: CallImportEvaluation,
    header: Dict[str, Any],
) -> Dict[str, Any]:
    """Align row/batch totals with the DB and repair legacy progress."""
    total_rows = count_completed_evaluation_row_pairs(db, evaluation.id)
    total_batches = batch_count_for_rows(total_rows)
    progress = header.get("progress") if isinstance(header.get("progress"), dict) else {}
    stored_batches = int(progress.get("completed_batches") or 0)
    completed_batches = min(stored_batches, total_batches) if total_batches else stored_batches
    completed_rows = rows_completed_for_batches(
        completed_batches, total_rows
    ) if total_rows else int(progress.get("completed_rows") or 0)
    llm_used = max(
        int(header.get("llm_calls_used") or 0),
        int(progress.get("completed_llm_calls") or 0),
    )
    phase = progress.get("phase") if isinstance(progress.get("phase"), str) else None
    if phase not in {"rows", "synthesis"}:
        phase = "synthesis" if total_batches > 0 and completed_batches >= total_batches else "rows"
    new_progress = progress_header(
        completed_rows=completed_rows,
        total_rows=total_rows,
        completed_batches=completed_batches,
        total_batches=total_batches,
        completed_llm_calls=llm_used,
        total_llm_calls=estimate_user_insights_total_llm_calls(total_rows),
        phase=phase,
    )
    return {
        **header,
        "progress": new_progress,
        "llm_calls_used": llm_used,
    }


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
    size: int | None = None,
) -> List[List[Dict[str, Any]]]:
    chunk = max(1, size if size is not None else extraction_sub_batch_size(len(rows)))
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
    """Run synthesis once over every durable batch checkpoint."""
    if is_cancelled and is_cancelled():
        return _cancelled_state(
            evaluation,
            raw_header,
            llm_calls_used=int(raw_header.get("llm_calls_used") or 0),
        )

    progress = raw_header.get("progress") if isinstance(raw_header.get("progress"), dict) else {}
    provider_label = provider.value if hasattr(provider, "value") else str(provider)

    # Synthesis is idempotent for a job run: if it already produced batches of
    # insight blocks we reuse them instead of paying for another LLM call.
    existing_batches = list_analysis_batches(
        db,
        evaluation_id=evaluation.id,
        job_kind=JOB_KIND_USER_INSIGHTS,
        job_run_id=job_run_id,
    )
    for batch in existing_batches:
        if (batch.status or "") != "synthesis_completed":
            continue
        payload = batch.payload if isinstance(batch.payload, dict) else {}
        if payload.get("insights") is not None:
            from app.models.schemas import EvaluationUserInsightItem

            insights = [
                EvaluationUserInsightItem.model_validate(item)
                for item in payload.get("insights") or []
                if isinstance(item, dict)
            ]
            if insights:
                return EvaluationUserInsightsState(
                    status="completed",
                    insights=insights,
                    overview=payload.get("overview"),
                    generated_at=datetime.now(timezone.utc),
                    generated_at_completed_rows=evaluation.completed_rows,
                    progress={**progress, "phase": "completed"},
                    provider=provider_label,
                    model=model,
                    llm_calls_used=int(raw_header.get("llm_calls_used") or 0),
                    is_stale=False,
                )

    batches = [
        b
        for b in existing_batches
        if (b.status or "") == "completed"
        and b.batch_index < SYNTHESIS_BATCH_INDEX_OFFSET
    ]
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
            provider=provider_label,
            model=model,
        )

    completed_calls += SYNTHESIS_CALLS
    upsert_analysis_batch(
        db,
        evaluation_id=evaluation.id,
        job_kind=JOB_KIND_USER_INSIGHTS,
        job_run_id=job_run_id,
        batch_index=SYNTHESIS_BATCH_INDEX_OFFSET,
        payload={
            "insights": [item.model_dump(mode="json") for item in insights],
            "overview": overview,
        },
        status="synthesis_completed",
    )

    final_progress = {
        **progress,
        "phase": "completed",
        "completed_llm_calls": completed_calls,
        "completed_rows": int(progress.get("total_rows") or total_sampled or 0),
        "completed_batches": int(progress.get("total_batches") or 0),
    }
    if on_progress:
        on_progress(final_progress)

    if not insights:
        return EvaluationUserInsightsState(
            status="failed",
            error_message="LLM returned no insight blocks.",
            generated_at=datetime.now(timezone.utc),
            llm_calls_used=completed_calls,
            progress=final_progress,
            provider=provider_label,
            model=model,
        )

    return EvaluationUserInsightsState(
        status="completed",
        insights=insights,
        overview=overview,
        generated_at=datetime.now(timezone.utc),
        generated_at_completed_rows=evaluation.completed_rows,
        progress=final_progress,
        provider=provider_label,
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

    raw = reconcile_user_insights_job_header(db, evaluation, raw)
    evaluation.user_insights = raw
    progress = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
    phase = str(progress.get("phase") or "rows")
    total_rows = int(progress.get("total_rows") or 0)
    total_batches = int(progress.get("total_batches") or 0)
    completed_batches = int(progress.get("completed_batches") or 0)
    llm_calls_used = int(raw.get("llm_calls_used") or 0)
    total_llm_calls = int(progress.get("total_llm_calls") or 0) or (
        estimate_user_insights_total_llm_calls(total_rows)
    )

    if phase == "synthesis" or (
        total_batches > 0 and completed_batches >= total_batches
    ):
        return "done", _finalize_synthesis(
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
                progress=progress,
            )
        raw["progress"] = {**progress, "phase": "synthesis"}
        evaluation.user_insights = raw
        return "done", _finalize_synthesis(
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
    rows_before_this_batch = rows_completed_for_batches(completed_batches, total_rows)
    sub_batches = _sub_batch_payloads(row_payloads)
    chunk_size = extraction_sub_batch_size(len(row_payloads)) if row_payloads else 0

    # Resume inside a page: a worker killed by a time limit or redeploy mid-page
    # must not re-pay for sub-batches that already checkpointed.
    done_sub_batches: set[int] = set()
    batch_extractions: List[Dict[str, Any]] = []
    for batch in list_analysis_batches(
        db,
        evaluation_id=evaluation.id,
        job_kind=JOB_KIND_USER_INSIGHTS,
        job_run_id=job_run_id,
    ):
        if batch.batch_index != batch_index or (batch.status or "") != "in_progress":
            continue
        payload = batch.payload if isinstance(batch.payload, dict) else {}
        raw_done = payload.get("sub_batches_done")
        if isinstance(raw_done, list):
            done_sub_batches = {
                int(idx) for idx in raw_done if isinstance(idx, (int, float))
            }
        restored = payload.get("extractions")
        if isinstance(restored, list):
            batch_extractions = [item for item in restored if isinstance(item, dict)]
        break
    batch_theme: Dict[str, int] = _aggregate_themes(batch_extractions)

    for sub_idx, sub_batch in enumerate(sub_batches):
        if sub_idx in done_sub_batches:
            continue
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
                    "rows_processed": len(pairs),
                    "rows_skipped_empty_transcript": skipped,
                    "sub_batches_done": sorted(done_sub_batches | {sub_idx}),
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
        if on_progress:
            processed_in_batch = min((sub_idx + 1) * chunk_size, len(row_payloads))
            on_progress(
                progress_header(
                    completed_rows=rows_before_this_batch + processed_in_batch,
                    total_rows=total_rows,
                    completed_batches=completed_batches,
                    total_batches=total_batches,
                    completed_llm_calls=llm_calls_used,
                    total_llm_calls=total_llm_calls,
                    phase="rows",
                )
            )

    if is_cancelled and is_cancelled():
        return "idle", _cancelled_state(
            evaluation, raw, llm_calls_used=llm_calls_used
        )

    page_cursor = evaluation_row_page_cursor_from_pair(pairs[-1])
    upsert_analysis_batch(
        db,
        evaluation_id=evaluation.id,
        job_kind=JOB_KIND_USER_INSIGHTS,
        job_run_id=job_run_id,
        batch_index=batch_index,
        payload={
            "extractions": batch_extractions,
            "theme_counts": batch_theme,
            "rows_processed": len(pairs),
            "rows_skipped_empty_transcript": skipped,
            "sub_batches_done": list(range(len(sub_batches))),
        },
        cursor=page_cursor,
        transcript_source=transcript_source,
        status="completed",
    )

    completed_batches += 1
    new_progress = progress_header(
        completed_rows=rows_completed_for_batches(completed_batches, total_rows),
        total_rows=total_rows,
        completed_batches=completed_batches,
        total_batches=total_batches,
        completed_llm_calls=llm_calls_used,
        total_llm_calls=total_llm_calls,
        phase="rows" if completed_batches < total_batches else "synthesis",
    )
    merge_theme_counts_into_header(raw, batch_theme)

    db.expire(evaluation, ["user_insights"])
    db.refresh(evaluation)
    live = evaluation.user_insights if isinstance(evaluation.user_insights, dict) else {}
    if user_insights_raw_is_cancelled(live):
        return "idle", _cancelled_state(
            evaluation, live, llm_calls_used=llm_calls_used
        )

    evaluation.user_insights = {
        **live,
        "status": "running",
        "progress": new_progress,
        "cursor": cursor_to_dict(page_cursor),
        "llm_calls_used": llm_calls_used,
        "theme_counts": raw.get("theme_counts", live.get("theme_counts")),
        "job_run_id": live.get("job_run_id") or raw.get("job_run_id"),
        "transcript_source": live.get("transcript_source") or raw.get("transcript_source"),
        "provider": live.get("provider") or raw.get("provider"),
        "model": live.get("model") or raw.get("model"),
    }

    if on_progress:
        on_progress(new_progress)

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
    header["progress"]["total_llm_calls"] = estimate_user_insights_total_llm_calls(
        total_rows
    )
    return header


def resume_user_insights_job_header(
    db: Session,
    evaluation: CallImportEvaluation,
    prior: Dict[str, Any],
    *,
    transcript_source: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-open a checkpointed job without resetting batch row progress."""
    header = dict(prior)
    header["status"] = "running"
    header["error_message"] = None
    header["celery_task_id"] = None
    header["transcript_source"] = normalize_transcript_source(transcript_source)
    if provider:
        header["provider"] = provider
    if model:
        header["model"] = model
    return reconcile_user_insights_job_header(db, evaluation, header)
