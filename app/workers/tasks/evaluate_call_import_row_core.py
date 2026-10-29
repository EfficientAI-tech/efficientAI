"""Shared helpers for call-import evaluation row tasks (audio + LLM phases)."""

from __future__ import annotations

import math
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy import and_, case, func, or_, update
from sqlalchemy.orm import Session, load_only

from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
)
from app.workers.tasks.helpers.constants import AUDIO_ONLY_METRIC_NAMES
from app.workers.tasks.helpers.llm_evaluation import MetricPromptGroup
from app.workers.tasks.helpers.score_utils import get_metric_type_value

EVAL_CANCELLED_BY_USER_ERROR: str = "Evaluation cancelled by user"

_BILLING_META_KEY = "_billing"

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


def claim_eval_row_for_task(
    row_db: Session,
    eval_row: CallImportEvaluationRow,
    task_id: str | None,
    predecessor_task_id: str | None = None,
) -> bool:
    """Mark the row running for this task.

    A second Celery task for the same row loses the update and must not
    call the model. The dispatcher writes ``celery_task_id`` while the
    row is still pending, so the match is on that id. The audio phase may
    hand a running row to the LLM task it just queued; that successor
    matches ``predecessor_task_id`` until the new id is stored.
    """
    cleaned = (task_id or "").strip()
    predecessor = (predecessor_task_id or "").strip()
    filters = [
        CallImportEvaluationRow.id == eval_row.id,
        CallImportEvaluationRow.status.in_(("pending", "running")),
    ]
    if cleaned:
        # Pending with no id can be taken once. Running only matches its task id.
        owner_match = [
            and_(
                CallImportEvaluationRow.status == "pending",
                CallImportEvaluationRow.celery_task_id.is_(None),
            ),
            CallImportEvaluationRow.celery_task_id == cleaned,
        ]
        if predecessor and predecessor != cleaned:
            owner_match.append(
                and_(
                    CallImportEvaluationRow.status == "running",
                    CallImportEvaluationRow.celery_task_id == predecessor,
                )
            )
        filters.append(or_(*owner_match))
    else:
        filters.append(CallImportEvaluationRow.status == "pending")
    values: dict[str, Any] = {
        "status": "running",
        "error_message": None,
        "started_at": func.coalesce(CallImportEvaluationRow.started_at, now_utc()),
    }
    if cleaned:
        values["celery_task_id"] = cleaned
    result = row_db.execute(
        update(CallImportEvaluationRow).where(*filters).values(**values)
    )
    if result.rowcount != 1:
        row_db.rollback()
        return False
    row_db.commit()
    row_db.refresh(eval_row)
    return True


_EXECUTION_TTL_SECONDS = 15 * 60


def _execution_key(task_id: str) -> str:
    return f"eval:execution:{task_id}"


def acquire_eval_execution(task_id: str | None) -> bool:
    """True when this delivery may call the model.

    A second delivery of the same task id loses. Redis errors allow the
    call so a lock outage does not skip a row that nobody else is scoring.
    """
    cleaned = (task_id or "").strip()
    if not cleaned:
        return True
    try:
        from app.workers.concurrency.limits import _get_redis

        acquired = _get_redis().set(
            _execution_key(cleaned),
            "1",
            nx=True,
            ex=_EXECUTION_TTL_SECONDS,
        )
    except Exception:
        return True
    return bool(acquired)


def release_eval_execution(task_id: str | None) -> None:
    cleaned = (task_id or "").strip()
    if not cleaned:
        return
    try:
        from app.workers.concurrency.limits import _get_redis

        _get_redis().delete(_execution_key(cleaned))
    except Exception:
        return


def as_json_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def was_cancelled_externally(db, eval_row: CallImportEvaluationRow) -> bool:
    """Re-read row status; True when the operator cancelled mid-flight."""
    try:
        db.expire(eval_row, ["status", "error_message"])
        db.refresh(eval_row, attribute_names=["status", "error_message"])
    except Exception:  # noqa: BLE001
        return False
    return is_eval_row_user_cancelled(eval_row)


def is_eval_row_user_cancelled(eval_row: CallImportEvaluationRow) -> bool:
    """True when the row was aborted by the operator."""
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


LlmConfigKey = tuple[str | None, str | None, str | None, str | None]


def _llm_config_key(cfg: dict | None) -> str | None:
    import json

    if not cfg:
        return None
    return json.dumps(cfg, sort_keys=True, default=str)


def resolve_metric_llm_config(
    metric: Metric,
    *,
    overrides: dict,
    run_provider: str | None,
    run_model: str | None,
    run_llm_config: dict | None,
    run_credential_id: str | None,
) -> LlmConfigKey:
    override = overrides.get(str(metric.id)) or {}
    provider = override.get("provider") or run_provider or None
    model = override.get("model") or run_model or None
    llm_cfg = override.get("llm_config") or run_llm_config
    credential_id = override.get("credential_id") or run_credential_id
    return (provider, model, _llm_config_key(llm_cfg), credential_id)


def build_metric_prompt_groups(
    db,
    metrics: list[Metric],
    *,
    running_discovered_by_parent: dict[UUID, list] | None = None,
) -> list[MetricPromptGroup]:
    parents_by_id, children_by_parent, standalone = build_parent_groups(db, metrics)
    discovered_map = running_discovered_by_parent or {}
    groups: list[MetricPromptGroup] = []
    if standalone:
        groups.append(MetricPromptGroup(None, standalone, None))
    for parent_id, children in children_by_parent.items():
        parent_metric = parents_by_id.get(parent_id)
        if parent_metric is None:
            groups.append(MetricPromptGroup(None, children, None))
        else:
            groups.append(
                MetricPromptGroup(
                    parent_metric,
                    children,
                    discovered_map.get(parent_id),
                )
            )
    return groups


def build_llm_config_buckets(
    db,
    metrics: list[Metric],
    *,
    overrides: dict,
    run_provider: str | None,
    run_model: str | None,
    run_llm_config: dict | None,
    run_credential_id: str | None,
    running_discovered_by_parent: dict[UUID, list] | None = None,
) -> dict[LlmConfigKey, list[MetricPromptGroup]]:
    """Group metrics by LLM config; each bucket holds prompt groups for one call."""
    buckets: dict[LlmConfigKey, list[Metric]] = {}
    for metric in metrics:
        key = resolve_metric_llm_config(
            metric,
            overrides=overrides,
            run_provider=run_provider,
            run_model=run_model,
            run_llm_config=run_llm_config,
            run_credential_id=run_credential_id,
        )
        buckets.setdefault(key, []).append(metric)

    return {
        config: build_metric_prompt_groups(
            db,
            bucket_metrics,
            running_discovered_by_parent=running_discovered_by_parent,
        )
        for config, bucket_metrics in buckets.items()
    }


def bucket_needs_comparison_pair(
    groups: list[MetricPromptGroup],
    *,
    production_transcript: str,
    diarised_transcript: str,
    comparison_metric_ids: set[str],
) -> bool:
    if not production_transcript or not diarised_transcript:
        return False
    for group in groups:
        if group.parent_metric is not None and metric_text_references_production(
            group.parent_metric
        ):
            return True
        for metric in group.metrics:
            if str(metric.id) in comparison_metric_ids:
                return True
            if metric_text_references_production(
                metric, parent=group.parent_metric
            ):
                return True
    return False


def count_distinct_llm_configs_for_metrics(
    metrics: list[Metric],
    *,
    overrides: dict,
    run_provider: str | None,
    run_model: str | None,
    run_llm_config: dict | None,
    run_credential_id: str | None,
) -> int:
    """Expected LLM calls per row (one per distinct LLM config among metrics)."""
    configs: set[LlmConfigKey] = set()
    for metric in metrics:
        if (metric.name or "").strip().lower() in AUDIO_ONLY_METRIC_NAMES:
            continue
        configs.add(
            resolve_metric_llm_config(
                metric,
                overrides=overrides,
                run_provider=run_provider,
                run_model=run_model,
                run_llm_config=run_llm_config,
                run_credential_id=run_credential_id,
            )
        )
    return len(configs)


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


def _should_confirm_eval_finished(
    evaluation_id: UUID,
    expected_in_progress: int,
) -> bool:
    """Whether to compare parent counters with the live row count.

    Mid-run the increment is enough. Confirm when the counter says the run
    is down to the last row, and when this task is the only one still in
    flight. A lost parent commit can leave the counter above 1 after every
    row is already terminal; that last task still has to close and bill.
    An inflight of 0 means this caller has no tracked slot, so it is not
    treated as the closer.
    """
    if expected_in_progress <= 1:
        return True
    from app.workers.concurrency.limits import read_job_inflight

    return read_job_inflight(evaluation_id) == 1


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

    if (evaluation.status or "").strip().lower() == "cancelled":
        if in_progress > 0:
            return
        evaluation.finished_at = now_utc()
        if total == 0 or failed == 0:
            evaluation.status = "completed"
        elif completed == 0:
            evaluation.status = "failed"
        else:
            evaluation.status = "partial"
        return

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


_EVALUATION_WORKER_COLUMNS = (
    CallImportEvaluation.id,
    CallImportEvaluation.call_import_id,
    CallImportEvaluation.organization_id,
    CallImportEvaluation.workspace_id,
    CallImportEvaluation.status,
    CallImportEvaluation.started_at,
    CallImportEvaluation.finished_at,
    CallImportEvaluation.error_message,
    CallImportEvaluation.total_rows,
    CallImportEvaluation.completed_rows,
    CallImportEvaluation.failed_rows,
    CallImportEvaluation.billed_completed_rows,
    CallImportEvaluation.selected_metric_ids,
    CallImportEvaluation.discover_new_metrics,
    CallImportEvaluation.discovered_metric_aliases,
    CallImportEvaluation.discovered_label_aliases,
    CallImportEvaluation.metric_llm_overrides,
    CallImportEvaluation.llm_provider,
    CallImportEvaluation.llm_model,
    CallImportEvaluation.llm_credential_id,
    CallImportEvaluation.llm_config,
    CallImportEvaluation.transcript_source,
)

_COUNTER_REFRESH_ATTRS = (
    "completed_rows",
    "failed_rows",
    "total_rows",
    "status",
    "billed_completed_rows",
    "started_at",
    "finished_at",
)


def load_evaluation_for_worker(
    db: Session,
    evaluation_id: UUID,
) -> CallImportEvaluation | None:
    """Parent row for scoring. Omits cached insight JSON the worker never reads."""
    return (
        db.query(CallImportEvaluation)
        .options(load_only(*_EVALUATION_WORKER_COLUMNS))
        .filter(CallImportEvaluation.id == evaluation_id)
        .first()
    )


def commit_terminal_row_and_rollup(
    row_db: Session,
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    *,
    previous_row_status: str,
    catalog_db: Session | None = None,
) -> None:
    from contextlib import nullcontext

    from app.db_sharding.row_ops import shard_row_write_context

    parent_db = catalog_db if catalog_db is not None and catalog_db is not row_db else row_db
    # Shard FK points at the catalogue evaluation; skip it for this write.
    write_ctx = (
        shard_row_write_context(row_db) if parent_db is not row_db else nullcontext()
    )
    with write_ctx:
        target_status = eval_row.status
        with row_db.no_autoflush:
            transition = row_db.execute(
                update(CallImportEvaluationRow)
                .where(
                    CallImportEvaluationRow.id == eval_row.id,
                    CallImportEvaluationRow.status.in_(("pending", "running")),
                )
                .values(status=target_status)
            )
        current = (
            row_db.query(CallImportEvaluationRow.status)
            .filter(CallImportEvaluationRow.id == eval_row.id)
            .scalar()
        )
        target = (target_status or "").lower()
        current_norm = (current or "").lower()
        if transition.rowcount not in (1, -1):
            if current_norm == target:
                return
            row_db.rollback()
            return
        if current_norm != target:
            row_db.rollback()
            return
        bill_after_commit = None
        if (eval_row.status or "").lower() == "completed":
            source_row = (
                row_db.query(CallImportRow)
                .filter(CallImportRow.id == eval_row.call_import_row_id)
                .first()
            )
            if source_row is not None:
                bill_after_commit = (evaluation, eval_row, source_row)
        row_db.flush()
        row_db.commit()
        row_db.refresh(eval_row)
    if bill_after_commit is not None:
        evaluation, eval_row, source_row = bill_after_commit
        from app.services.call_imports.eval_flexprice_billing import (
            maybe_enqueue_recording_minutes_for_completed_row,
        )

        maybe_enqueue_recording_minutes_for_completed_row(
            row_db,
            evaluation,
            eval_row,
            source_row=source_row,
            resolve_audio_seconds=resolve_eval_row_audio_seconds,
            billable_minutes_fn=billable_audio_minutes,
        )
    if (eval_row.status or "").lower() == "completed":
        from app.services.call_imports.discovered_running_cache import (
            record_row_discoveries,
        )

        record_row_discoveries(
            evaluation.id,
            eval_row.id,
            eval_row.metric_scores,
        )
    if parent_db is not row_db:
        evaluation = load_evaluation_for_worker(parent_db, evaluation.id)
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
            counter_update = (
                update(CallImportEvaluation)
                .where(CallImportEvaluation.id == evaluation_id)
                .values(
                    completed_rows=CallImportEvaluation.completed_rows
                    + completed_delta,
                    failed_rows=CallImportEvaluation.failed_rows + failed_delta,
                )
            )
            previous_completed = int(evaluation.completed_rows or 0)
            previous_failed = int(evaluation.failed_rows or 0)
            bind = db.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                returned = db.execute(
                    counter_update.returning(
                        CallImportEvaluation.completed_rows,
                        CallImportEvaluation.failed_rows,
                    )
                ).one()
                evaluation.completed_rows = int(returned[0] or 0)
                evaluation.failed_rows = int(returned[1] or 0)
            else:
                db.execute(counter_update)
                evaluation.completed_rows = previous_completed + completed_delta
                evaluation.failed_rows = previous_failed + failed_delta
            db.flush()
    else:
        reconcile_evaluation_counters(db, evaluation)

    from app.services.call_imports.progress_counters import clear_eval_progress_redis

    clear_eval_progress_redis(evaluation_id)

    if previous_row_status is None or new_row_status is None:
        db.refresh(evaluation, attribute_names=list(_COUNTER_REFRESH_ATTRS))
    if previous_row_status is not None and new_row_status is not None:
        expected_in_progress = (
            int(evaluation.total_rows or 0)
            - int(evaluation.completed_rows or 0)
            - int(evaluation.failed_rows or 0)
        )
        if _should_confirm_eval_finished(
            evaluation_id, expected_in_progress
        ) and expected_in_progress != _count_in_progress_rows(db, evaluation_id):
            reconcile_evaluation_counters(db, evaluation)
            db.refresh(evaluation, attribute_names=list(_COUNTER_REFRESH_ATTRS))

    _apply_parent_status_from_counters(evaluation)

    if previous_row_status is not None and new_row_status is not None:
        from app.services.call_imports.metric_aggregate_cache import (
            maybe_refresh_aggregate_cache_after_row,
        )

        maybe_refresh_aggregate_cache_after_row(
            db,
            evaluation,
            new_row_status=new_row_status,
        )

    total = int(evaluation.total_rows or 0)
    completed = int(evaluation.completed_rows or 0)
    failed = int(evaluation.failed_rows or 0)
    in_progress = total - completed - failed
    if in_progress > 0:
        return

    already_billed = int(getattr(evaluation, "billed_completed_rows", 0) or 0)
    delta = completed - already_billed
    if delta > 0:
        evaluation = (
            db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == evaluation_id)
            .with_for_update()
            .one()
        )
        from app.services.call_imports.eval_flexprice_billing import (
            buffer_call_import_evaluation_pass,
        )

        billing_accepted = buffer_call_import_evaluation_pass(
            evaluation,
            rows_billed=delta,
            completed_total=completed,
        )
        if billing_accepted:
            evaluation.billed_completed_rows = completed


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

    from app.workers.catalog_cache import cached_catalog_fetch

    cache_key = (
        f"{evaluation.organization_id}:"
        + ",".join(sorted(str(mid) for mid in metric_ids))
    )

    def _load() -> list[Metric]:
        rows = (
            db.query(Metric)
            .filter(
                Metric.organization_id == evaluation.organization_id,
                Metric.id.in_(metric_ids),
                Metric.enabled.is_(True),
                or_(Metric.lifecycle.is_(None), Metric.lifecycle == "active"),
            )
            .all()
        )
        for row in rows:
            db.expunge(row)
        return rows

    return list(cached_catalog_fetch("enabled_metrics", cache_key, _load))


def load_active_ai_providers(db: Session, organization_id: UUID) -> list:
    """Active org providers, cached so each scoring call does not re-read them."""
    from app.models.database import AIProvider
    from app.workers.catalog_cache import cached_catalog_fetch

    def _load() -> list:
        rows = (
            db.query(AIProvider)
            .filter(
                AIProvider.organization_id == organization_id,
                AIProvider.is_active.is_(True),
            )
            .all()
        )
        for row in rows:
            db.expunge(row)
        return rows

    return list(
        cached_catalog_fetch("active_ai_providers", str(organization_id), _load)
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
    from app.db_sharding.scatter_gather import row_text_present

    production_transcript = row_text_present(
        source_row, "transcript", "transcript_char_length"
    )
    diarised_transcript = row_text_present(
        source_row, "diarised_transcript", "diarised_transcript_char_length"
    )
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


def cache_eval_row_audio_seconds(
    eval_row: CallImportEvaluationRow,
    audio_seconds: int,
) -> None:
    merged = dict(eval_row.metric_scores or {})
    billing = dict(merged.get(_BILLING_META_KEY) or {})
    billing["audio_seconds"] = max(0, int(audio_seconds))
    merged[_BILLING_META_KEY] = billing
    eval_row.metric_scores = merged


def get_cached_eval_row_audio_seconds(eval_row: CallImportEvaluationRow) -> int:
    merged = eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
    billing = merged.get(_BILLING_META_KEY) or {}
    if not isinstance(billing, dict):
        return 0
    try:
        return max(0, int(billing.get("audio_seconds") or 0))
    except (TypeError, ValueError):
        return 0


def billable_audio_minutes(audio_seconds: int) -> int:
    seconds = max(0, int(audio_seconds or 0))
    if seconds <= 0:
        return 0
    return max(1, math.ceil(seconds / 60))


def probe_recording_audio_seconds(recording_s3_key: str) -> int:
    from app.services.storage.s3_service import s3_service
    from app.services.usage.llm_usage import probe_audio_seconds

    key = (recording_s3_key or "").strip()
    if not key:
        return 0
    audio_bytes = s3_service.download_file_by_key(key)
    if not audio_bytes:
        return 0
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
    os.close(tmp_fd)
    try:
        with open(tmp_path, "wb") as handle:
            handle.write(audio_bytes)
        return probe_audio_seconds(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def resolve_eval_row_audio_seconds(
    db: Session,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow | None,
) -> int:
    cached = get_cached_eval_row_audio_seconds(eval_row)
    if cached > 0:
        return cached
    if source_row is None:
        source_row = (
            db.query(CallImportRow)
            .filter(CallImportRow.id == eval_row.call_import_row_id)
            .first()
        )
    if source_row is None:
        return 0
    stored = getattr(source_row, "recording_duration_seconds", None)
    if stored is not None and int(stored) > 0:
        seconds = int(stored)
        cache_eval_row_audio_seconds(eval_row, seconds)
        return seconds
    return 0

