"""Shared helpers for call-import evaluation row tasks (audio + LLM phases)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy import case, func, update
from sqlalchemy.orm import Session

from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
)
from app.workers.tasks.helpers.constants import AUDIO_ONLY_METRIC_NAMES
from app.workers.tasks.helpers.score_utils import get_metric_type_value

EVAL_CANCELLED_BY_USER_ERROR: str = "Evaluation cancelled by user"

_ALL_COLUMNS_BLOCK_MAX_CHARS = 16_000
_ALL_COLUMNS_CELL_MAX_CHARS = 4_000

_PROD_KEYWORDS: tuple[str, ...] = (
    "production transcript",
    "prod transcript",
    "diarised transcript",
    "diarized transcript",
    "compare transcripts",
    "compare the transcripts",
    "compare both transcripts",
    "both transcripts",
    "two transcripts",
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_json_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def was_cancelled_externally(db, eval_row: CallImportEvaluationRow) -> bool:
    """Re-read row status; True when the operator cancelled mid-flight."""
    try:
        db.expire(eval_row, ["status", "error_message"])
        db.refresh(eval_row, attribute_names=["status", "error_message"])
    except Exception:  # noqa: BLE001
        return False
    return (
        (eval_row.status or "").lower() == "failed"
        and (eval_row.error_message or "") == EVAL_CANCELLED_BY_USER_ERROR
    )


def metric_text_references_production(
    metric: Metric, parent: Metric | None = None
) -> bool:
    blobs: list[str] = []
    desc = getattr(metric, "description", None)
    if isinstance(desc, str) and desc:
        blobs.append(desc)
    if parent is not None:
        parent_desc = getattr(parent, "description", None)
        if isinstance(parent_desc, str) and parent_desc:
            blobs.append(parent_desc)
    if not blobs:
        return False
    blob = " ".join(blobs).lower()
    return any(kw in blob for kw in _PROD_KEYWORDS)


def build_all_columns_block(
    raw_columns: dict[str, Any] | None,
    custom_column_mapping: dict[str, Any] | None = None,
) -> str | None:
    if not isinstance(raw_columns, dict) or not raw_columns:
        return None

    mapping = (
        custom_column_mapping
        if isinstance(custom_column_mapping, dict)
        else {}
    )
    friendly_for_header: dict[str, str] = {}
    for friendly, csv_header in mapping.items():
        if isinstance(friendly, str) and isinstance(csv_header, str):
            friendly_for_header.setdefault(csv_header, friendly)

    lines: list[str] = []
    total = 0
    for header, value in raw_columns.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if len(text) > _ALL_COLUMNS_CELL_MAX_CHARS:
            text = text[: _ALL_COLUMNS_CELL_MAX_CHARS] + "…"
        friendly = friendly_for_header.get(str(header))
        label = (
            f"{header} (a.k.a. {friendly})"
            if friendly and friendly != header
            else str(header)
        )
        line = f"- {label}: {text}"
        if total + len(line) + 1 > _ALL_COLUMNS_BLOCK_MAX_CHARS:
            lines.append("- … (additional columns truncated to keep prompt size bounded)")
            break
        lines.append(line)
        total += len(line) + 1

    if not lines:
        return None
    return "\n".join(lines)


def categorize_metrics(
    metrics: list[Metric],
    has_audio: bool,
    has_production_transcript: bool = False,
    has_diarised_transcript: bool = False,
) -> tuple[
    list[Metric],
    list[Metric],
    list[Metric],
    dict[str, dict[str, Any]],
]:
    transcript_metrics: list[Metric] = []
    audio_metrics: list[Metric] = []
    comparison_metrics: list[Metric] = []
    skipped_scores: dict[str, dict[str, Any]] = {}

    for m in metrics:
        normalized = (m.name or "").strip().lower()
        if normalized in AUDIO_ONLY_METRIC_NAMES:
            if has_audio:
                audio_metrics.append(m)
            else:
                skipped_scores[str(m.id)] = {
                    "value": None,
                    "type": get_metric_type_value(m),
                    "metric_name": m.name,
                    "skipped": "audio_required",
                }
            continue

        is_explicit_compare = bool(getattr(m, "compare_transcripts", False))
        is_standalone = not getattr(m, "parent_metric_id", None)
        is_auto_compare = (
            is_standalone
            and has_production_transcript
            and has_diarised_transcript
            and metric_text_references_production(m)
        )
        if is_explicit_compare or is_auto_compare:
            missing: list[str] = []
            if not has_production_transcript:
                missing.append("production")
            if not has_diarised_transcript:
                missing.append("diarised")
            if missing:
                skipped_scores[str(m.id)] = {
                    "value": None,
                    "type": get_metric_type_value(m),
                    "metric_name": m.name,
                    "skipped": "comparison_missing_transcript",
                    "missing_transcripts": missing,
                }
                continue
            comparison_metrics.append(m)
            continue

        transcript_metrics.append(m)

    return (
        transcript_metrics,
        audio_metrics,
        comparison_metrics,
        skipped_scores,
    )


def build_parent_groups(
    db, llm_metrics: list[Metric]
) -> tuple[dict[UUID, Metric], dict[UUID, list[Metric]], list[Metric]]:
    children_by_parent: dict[UUID, list[Metric]] = {}
    standalone: list[Metric] = []
    for m in llm_metrics:
        if m.parent_metric_id:
            children_by_parent.setdefault(m.parent_metric_id, []).append(m)
        else:
            standalone.append(m)

    parents_by_id: dict[UUID, Metric] = {}
    if children_by_parent:
        rows = (
            db.query(Metric)
            .filter(Metric.id.in_(list(children_by_parent.keys())))
            .all()
        )
        parents_by_id = {row.id: row for row in rows}
        orphaned: list[UUID] = []
        for pid in list(children_by_parent.keys()):
            if pid not in parents_by_id:
                orphaned.append(pid)
        for pid in orphaned:
            standalone.extend(children_by_parent.pop(pid))

    return parents_by_id, children_by_parent, standalone


_TERMINAL_ROW_STATUSES = frozenset({"completed", "failed"})


def counter_deltas_for_status_transition(
    previous_status: str | None,
    new_status: str,
) -> tuple[int, int]:
    """Return ``(completed_delta, failed_delta)`` for a row status change."""
    previous = (previous_status or "").strip().lower()
    new = new_status.strip().lower()
    completed_delta = 0
    failed_delta = 0
    if previous in _TERMINAL_ROW_STATUSES:
        if previous == "completed":
            completed_delta -= 1
        else:
            failed_delta -= 1
    if new in _TERMINAL_ROW_STATUSES:
        if new == "completed":
            completed_delta += 1
        else:
            failed_delta += 1
    return completed_delta, failed_delta


def reconcile_evaluation_counters(
    db: Session,
    evaluation: CallImportEvaluation,
) -> None:
    """Sync parent counters from child rows using aggregate queries."""
    from app.db_sharding.sessions import is_sharding_enabled

    if is_sharding_enabled():
        from app.db_sharding.scatter_gather import aggregate_evaluation_row_counts

        total, completed, failed = aggregate_evaluation_row_counts(db, evaluation.id)
    else:
        counts = (
            db.query(
                func.count().label("total"),
                func.coalesce(
                    func.sum(
                        case(
                            (CallImportEvaluationRow.status == "completed", 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("completed"),
                func.coalesce(
                    func.sum(
                        case(
                            (CallImportEvaluationRow.status == "failed", 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("failed"),
            )
            .filter(CallImportEvaluationRow.evaluation_id == evaluation.id)
            .one()
        )
        total = int(counts.total or 0)
        completed = int(counts.completed or 0)
        failed = int(counts.failed or 0)

    db.execute(
        update(CallImportEvaluation)
        .where(CallImportEvaluation.id == evaluation.id)
        .values(
            total_rows=total,
            completed_rows=completed,
            failed_rows=failed,
        )
    )
    db.flush()
    db.refresh(evaluation)
    from app.services.call_imports.progress_counters import clear_eval_progress_redis

    clear_eval_progress_redis(evaluation.id)


def _count_in_progress_rows(db: Session, evaluation_id: UUID) -> int:
    """Count rows still pending or running (cheap indexed query)."""
    from app.db_sharding.sessions import is_sharding_enabled

    if is_sharding_enabled():
        from app.db_sharding.scatter_gather import count_eval_rows_in_progress

        return count_eval_rows_in_progress(db, evaluation_id)

    return int(
        db.query(func.count())
        .filter(
            CallImportEvaluationRow.evaluation_id == evaluation_id,
            CallImportEvaluationRow.status.in_(["pending", "running"]),
        )
        .scalar()
        or 0
    )


def _apply_parent_status_from_counters(
    evaluation: CallImportEvaluation,
) -> None:
    total = int(evaluation.total_rows or 0)
    completed = int(evaluation.completed_rows or 0)
    failed = int(evaluation.failed_rows or 0)
    in_progress = total - completed - failed

    if in_progress > 0:
        evaluation.status = "running"
        if not evaluation.started_at:
            evaluation.started_at = now_utc()
        return

    evaluation.finished_at = now_utc()
    if total == 0:
        evaluation.status = "completed"
    elif failed == 0:
        evaluation.status = "completed"
    elif completed == 0:
        evaluation.status = "failed"
    else:
        evaluation.status = "partial"


def commit_terminal_row_and_rollup(
    row_db: Session,
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    *,
    previous_row_status: str,
    catalog_db: Session | None = None,
) -> None:
    parent_db = catalog_db if catalog_db is not None and catalog_db is not row_db else row_db
    row_db.commit()
    if parent_db is not row_db:
        evaluation = (
            parent_db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == evaluation.id)
            .first()
        )
        if evaluation is None:
            return
    rollup_parent(
        parent_db,
        evaluation,
        previous_row_status=previous_row_status,
        new_row_status=eval_row.status,
    )
    parent_db.commit()


def rollup_parent(
    db: Session,
    evaluation: CallImportEvaluation,
    *,
    previous_row_status: str | None = None,
    new_row_status: str | None = None,
) -> None:
    """Update parent counters and terminal status after a row finishes.

    When ``previous_row_status`` and ``new_row_status`` are supplied (worker
    hot path), counters are incremented atomically without scanning all rows.
    Otherwise counters are reconciled with a single aggregate query (API
    retries, row deletes, tests).
    """
    evaluation_id = evaluation.id
    if previous_row_status is not None and new_row_status is not None:
        completed_delta, failed_delta = counter_deltas_for_status_transition(
            previous_row_status,
            new_row_status,
        )
        if completed_delta or failed_delta:
            db.execute(
                update(CallImportEvaluation)
                .where(CallImportEvaluation.id == evaluation_id)
                .values(
                    completed_rows=CallImportEvaluation.completed_rows
                    + completed_delta,
                    failed_rows=CallImportEvaluation.failed_rows + failed_delta,
                )
            )
            db.flush()
    else:
        reconcile_evaluation_counters(db, evaluation)

    from app.services.call_imports.progress_counters import clear_eval_progress_redis

    clear_eval_progress_redis(evaluation_id)

    db.refresh(evaluation)
    if previous_row_status is not None and new_row_status is not None:
        expected_in_progress = (
            int(evaluation.total_rows or 0)
            - int(evaluation.completed_rows or 0)
            - int(evaluation.failed_rows or 0)
        )
        if expected_in_progress != _count_in_progress_rows(db, evaluation_id):
            reconcile_evaluation_counters(db, evaluation)
            db.refresh(evaluation)

    completed = int(evaluation.completed_rows or 0)
    already_billed = int(getattr(evaluation, "billed_completed_rows", 0) or 0)
    delta = completed - already_billed
    if delta > 0:
        evaluation = (
            db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == evaluation_id)
            .with_for_update()
            .one()
        )
        from app.services.billing.flexprice_service import (
            record_call_import_evaluation_completed,
        )

        metric_count = len(evaluation.selected_metric_ids or [])
        billing_accepted = record_call_import_evaluation_completed(
            evaluation.organization_id,
            evaluation.id,
            workspace_id=evaluation.workspace_id,
            call_import_id=evaluation.call_import_id,
            rows_billed=delta,
            completed_total=completed,
            metric_count=metric_count,
        )
        if billing_accepted:
            evaluation.billed_completed_rows = completed

    _apply_parent_status_from_counters(evaluation)


def parse_restricted_metric_uuids(
    restricted_metric_ids: Optional[List[str]],
) -> Optional[List[UUID]]:
    if not restricted_metric_ids:
        return None
    uuids: list[UUID] = []
    for raw in restricted_metric_ids:
        try:
            uuids.append(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    return uuids or None


def load_enabled_metrics(
    db: Session,
    evaluation: CallImportEvaluation,
    *,
    restricted_metric_ids: Optional[List[str]] = None,
) -> list[Metric]:
    metric_ids_raw = evaluation.selected_metric_ids or []
    metric_ids: list[UUID] = []
    for item in metric_ids_raw:
        try:
            metric_ids.append(UUID(str(item)))
        except (TypeError, ValueError):
            continue

    restricted_uuids = parse_restricted_metric_uuids(restricted_metric_ids)
    if restricted_uuids is not None:
        restricted_set = set(restricted_uuids)
        metric_ids = [mid for mid in metric_ids if mid in restricted_set]

    if not metric_ids:
        return []

    return (
        db.query(Metric)
        .filter(
            Metric.organization_id == evaluation.organization_id,
            Metric.id.in_(metric_ids),
            Metric.enabled.is_(True),
        )
        .all()
    )


def categorize_row_metrics(
    db: Session,
    evaluation: CallImportEvaluation,
    source_row: CallImportRow,
    metrics: list[Metric],
) -> tuple[
    list[Metric],
    list[Metric],
    list[Metric],
    dict[str, dict[str, Any]],
]:
    production_transcript = (source_row.transcript or "").strip()
    diarised_transcript = (source_row.diarised_transcript or "").strip()
    recording_s3_key = (source_row.recording_s3_key or "").strip() or None
    has_audio = recording_s3_key is not None
    return categorize_metrics(
        metrics,
        has_audio,
        has_production_transcript=bool(production_transcript),
        has_diarised_transcript=bool(diarised_transcript),
    )


def row_needs_audio_phase(
    db: Session,
    evaluation: CallImportEvaluation,
    source_row: CallImportRow,
    *,
    restricted_metric_ids: Optional[List[str]] = None,
) -> bool:
    metrics = load_enabled_metrics(
        db, evaluation, restricted_metric_ids=restricted_metric_ids
    )
    if not metrics:
        return False
    _, audio_metrics, _, _ = categorize_row_metrics(
        db, evaluation, source_row, metrics
    )
    return bool(audio_metrics)


def row_needs_llm_phase(
    db: Session,
    evaluation: CallImportEvaluation,
    source_row: CallImportRow,
    *,
    restricted_metric_ids: Optional[List[str]] = None,
) -> bool:
    metrics = load_enabled_metrics(
        db, evaluation, restricted_metric_ids=restricted_metric_ids
    )
    if not metrics:
        return False
    transcript_metrics, _audio, comparison_metrics, _ = categorize_row_metrics(
        db, evaluation, source_row, metrics
    )
    return bool(transcript_metrics or comparison_metrics)
