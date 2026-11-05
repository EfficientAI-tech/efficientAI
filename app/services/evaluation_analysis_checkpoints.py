"""Persist and load durable batch checkpoints for evaluation analysis jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.db_sharding.scatter_gather import (
    EVALUATION_ANALYSIS_BATCH_SIZE,
    EvaluationRowPageCursor,
    count_completed_evaluation_row_pairs,
)
from app.models.database import EvaluationAnalysisBatch

JobKind = Literal["user_insights", "metric_clusters", "prompt_improvements"]

JOB_KIND_USER_INSIGHTS: JobKind = "user_insights"
JOB_KIND_METRIC_CLUSTERS: JobKind = "metric_clusters"
JOB_KIND_PROMPT_IMPROVEMENTS: JobKind = "prompt_improvements"

USER_INSIGHTS_CANCELLED_BY_USER_ERROR = "Cancelled by user"
PROMPT_IMPROVEMENTS_CANCELLED_BY_USER_ERROR = "Cancelled by user"

EVIDENCE_RESERVOIR_CAP = 80


def analysis_header_matches_run(raw: Any, job_run_id: Any) -> bool:
    """True when *job_run_id* still owns the saved analysis header.

    A missing claim matches any header (the first enqueue, before a run
    id exists). A claim against a different header means this task is
    stale and must not write.
    """
    if job_run_id is None or str(job_run_id).strip() == "":
        return True
    if not isinstance(raw, dict):
        return False
    current = raw.get("job_run_id")
    if not current:
        return False
    return str(current) == str(job_run_id)


def new_job_run_id() -> UUID:
    return uuid4()


def normalize_transcript_source(value: Optional[str]) -> str:
    source = (value or "diarised").strip().lower()
    return source if source in {"diarised", "production"} else "diarised"


def batch_count_for_rows(total_rows: int, batch_size: int = EVALUATION_ANALYSIS_BATCH_SIZE) -> int:
    if total_rows <= 0:
        return 0
    return (total_rows + batch_size - 1) // batch_size


def progress_header(
    *,
    completed_rows: int,
    total_rows: int,
    completed_batches: int,
    total_batches: int,
    completed_llm_calls: int = 0,
    total_llm_calls: int = 0,
    phase: Optional[str] = None,
) -> Dict[str, Any]:
    if total_rows > 0:
        completed_rows = min(int(completed_rows), int(total_rows))
    if total_batches > 0:
        completed_batches = min(int(completed_batches), int(total_batches))
    payload: Dict[str, Any] = {
        "completed_rows": completed_rows,
        "total_rows": total_rows,
        "completed_batches": completed_batches,
        "total_batches": total_batches,
        "completed_llm_calls": completed_llm_calls,
        "total_llm_calls": total_llm_calls,
    }
    if phase:
        payload["phase"] = phase
    return payload


def rows_completed_for_batches(
    completed_batches: int,
    total_rows: int,
    *,
    batch_size: int = EVALUATION_ANALYSIS_BATCH_SIZE,
) -> int:
    """Rows finished after ``completed_batches`` full pages (never exceeds total)."""
    if total_rows <= 0 or completed_batches <= 0:
        return 0
    return min(int(total_rows), int(completed_batches) * int(batch_size))


def cursor_from_header(raw: Any) -> Optional[EvaluationRowPageCursor]:
    if not isinstance(raw, dict):
        return None
    cursor = raw.get("cursor")
    if not isinstance(cursor, dict):
        return None
    row_index = cursor.get("row_index")
    eval_row_id = cursor.get("evaluation_row_id")
    if not isinstance(row_index, (int, float)) or not eval_row_id:
        return None
    try:
        return EvaluationRowPageCursor(
            row_index=int(row_index),
            evaluation_row_id=UUID(str(eval_row_id)),
        )
    except (TypeError, ValueError):
        return None


def cursor_to_dict(cursor: EvaluationRowPageCursor) -> Dict[str, Any]:
    return {
        "row_index": cursor.row_index,
        "evaluation_row_id": str(cursor.evaluation_row_id),
    }


def user_insights_raw_is_cancelled(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    if (raw.get("status") or "").lower() == "cancelled":
        return True
    return raw.get("error_message") == USER_INSIGHTS_CANCELLED_BY_USER_ERROR


def prompt_improvements_raw_is_cancelled(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    if (raw.get("status") or "").lower() == "cancelled":
        return True
    return raw.get("error_message") == PROMPT_IMPROVEMENTS_CANCELLED_BY_USER_ERROR


def upsert_analysis_batch(
    db: Session,
    *,
    evaluation_id: UUID,
    job_kind: JobKind,
    job_run_id: UUID,
    batch_index: int,
    payload: Dict[str, Any],
    cursor: Optional[EvaluationRowPageCursor] = None,
    transcript_source: Optional[str] = None,
    status: str = "completed",
) -> EvaluationAnalysisBatch:
    row = (
        db.query(EvaluationAnalysisBatch)
        .filter(
            EvaluationAnalysisBatch.evaluation_id == evaluation_id,
            EvaluationAnalysisBatch.job_kind == job_kind,
            EvaluationAnalysisBatch.job_run_id == job_run_id,
            EvaluationAnalysisBatch.batch_index == batch_index,
        )
        .first()
    )
    if row is None:
        row = EvaluationAnalysisBatch(
            evaluation_id=evaluation_id,
            job_kind=job_kind,
            job_run_id=job_run_id,
            batch_index=batch_index,
        )
        db.add(row)
    row.payload = payload
    row.status = status
    row.transcript_source = transcript_source
    if cursor is not None:
        row.cursor_row_index = cursor.row_index
        row.cursor_evaluation_row_id = cursor.evaluation_row_id
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    return row


def list_analysis_batches(
    db: Session,
    *,
    evaluation_id: UUID,
    job_kind: JobKind,
    job_run_id: UUID,
) -> List[EvaluationAnalysisBatch]:
    return (
        db.query(EvaluationAnalysisBatch)
        .filter(
            EvaluationAnalysisBatch.evaluation_id == evaluation_id,
            EvaluationAnalysisBatch.job_kind == job_kind,
            EvaluationAnalysisBatch.job_run_id == job_run_id,
        )
        .order_by(EvaluationAnalysisBatch.batch_index)
        .all()
    )


def merge_theme_counts_from_batches(batches: List[EvaluationAnalysisBatch]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for batch in batches:
        if (getattr(batch, "status", None) or "completed") != "completed":
            continue
        payload = batch.payload if isinstance(batch.payload, dict) else {}
        partial = payload.get("theme_counts")
        if isinstance(partial, dict):
            for key, value in partial.items():
                label = str(key).strip()
                if not label:
                    continue
                try:
                    counts[label] = counts.get(label, 0) + int(value)
                except (TypeError, ValueError):
                    continue
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def merge_extractions_from_batches(
    batches: List[EvaluationAnalysisBatch],
    *,
    cap: int = EVIDENCE_RESERVOIR_CAP,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for batch in batches:
        if (getattr(batch, "status", None) or "completed") != "completed":
            continue
        payload = batch.payload if isinstance(batch.payload, dict) else {}
        samples = payload.get("extractions")
        if not isinstance(samples, list):
            continue
        for item in samples:
            if isinstance(item, dict):
                out.append(item)
            if len(out) >= cap:
                return out
    return out


def merge_signature_counts_from_cluster_batches(
    batches: List[EvaluationAnalysisBatch],
) -> Dict[str, Dict[str, int]]:
    """metric_id -> signature label -> count."""
    by_metric: Dict[str, Dict[str, int]] = {}
    for batch in batches:
        if (getattr(batch, "status", None) or "completed") != "completed":
            continue
        payload = batch.payload if isinstance(batch.payload, dict) else {}
        metrics_raw = payload.get("metrics")
        if not isinstance(metrics_raw, dict):
            continue
        for metric_id, sig_map in metrics_raw.items():
            if not isinstance(sig_map, dict):
                continue
            bucket = by_metric.setdefault(str(metric_id), {})
            for label, count in sig_map.items():
                name = str(label).strip()
                if not name:
                    continue
                try:
                    bucket[name] = bucket.get(name, 0) + int(count)
                except (TypeError, ValueError):
                    continue
    return by_metric


def merge_cluster_extractions_from_batches(
    batches: List[EvaluationAnalysisBatch],
    metric_id: str,
    *,
    cap: int = 40,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for batch in batches:
        if (getattr(batch, "status", None) or "completed") != "completed":
            continue
        payload = batch.payload if isinstance(batch.payload, dict) else {}
        metrics_raw = payload.get("metric_extractions")
        if not isinstance(metrics_raw, dict):
            continue
        samples = metrics_raw.get(metric_id)
        if not isinstance(samples, list):
            continue
        for item in samples:
            if isinstance(item, dict):
                out.append(item)
            if len(out) >= cap:
                return out
    return out


def init_job_header(
    *,
    job_run_id: UUID,
    transcript_source: str,
    total_rows: int,
    total_batches: int,
    provider: Optional[str],
    model: Optional[str],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    header: Dict[str, Any] = {
        "status": "running",
        "job_run_id": str(job_run_id),
        "transcript_source": transcript_source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "progress": progress_header(
            completed_rows=0,
            total_rows=total_rows,
            completed_batches=0,
            total_batches=total_batches,
        ),
        "theme_counts": {},
        "provider": provider,
        "model": model,
        "error_message": None,
        "celery_task_id": None,
    }
    if extra:
        header.update(extra)
    return header


def completed_rows_from_batches(batches: List[EvaluationAnalysisBatch]) -> int:
    total = 0
    seen: set[int] = set()
    for batch in batches:
        if (getattr(batch, "status", None) or "completed") != "completed":
            continue
        if batch.batch_index in seen:
            continue
        seen.add(batch.batch_index)
        payload = batch.payload if isinstance(batch.payload, dict) else {}
        try:
            total += int(payload.get("rows_processed") or 0)
        except (TypeError, ValueError):
            continue
    return total
