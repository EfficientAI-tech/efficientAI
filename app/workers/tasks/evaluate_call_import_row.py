"""Celery task: evaluate one CallImport row against selected metrics.

Metric routing mirrors ``process_evaluator_result``:

* Audio-only metrics (MOS Score, Pitch Variance, Jitter, Shimmer, HNR,
  Emotion Category/Confidence, Valence, Arousal, Speaker Consistency,
  Prosody Score) are dispatched through
  :func:`app.workers.tasks.helpers.audio_evaluation.evaluate_audio_metrics`,
  which downloads the recording from S3 and hands it to the actual signal
  processing libraries (Praat / UTMOS / qualitative voice service).
* The remaining metrics are evaluated against the transcript by the LLM
  helper, which is the appropriate medium for content-quality metrics.

Previously every metric was handed to the LLM, which meant scores like
"MOS" were hallucinated from transcript text instead of being measured
from the audio.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.models.database import (
    AIProvider,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
)
from app.workers.config import celery_app
from app.workers.tasks.helpers.audio_evaluation import (
    evaluate_audio_metrics,
    handle_audio_evaluation_error,
)
from app.workers.tasks.helpers.constants import AUDIO_ONLY_METRIC_NAMES
from app.workers.tasks.helpers.llm_evaluation import (
    evaluate_with_llm,
    handle_llm_evaluation_error,
)
from app.workers.tasks.helpers.score_utils import get_metric_type_value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_json_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _categorize_metrics(
    metrics: list[Metric], has_audio: bool
) -> tuple[list[Metric], list[Metric], dict[str, dict[str, Any]]]:
    """Split selected metrics into LLM vs audio buckets.

    Audio-only metrics that cannot be evaluated (no recording available
    on the row) are returned as pre-built "skipped" score entries so
    they still surface in the UI with an explanation rather than being
    silently dropped or routed to the LLM.
    """

    llm_metrics: list[Metric] = []
    audio_metrics: list[Metric] = []
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
        else:
            llm_metrics.append(m)

    return llm_metrics, audio_metrics, skipped_scores


def _build_parent_groups(
    db, llm_metrics: list[Metric]
) -> tuple[dict[UUID, Metric], dict[UUID, list[Metric]], list[Metric]]:
    """Group LLM metrics by their parent_metric_id.

    Children of the same parent are evaluated together in one LLM call
    so the model can enforce mutex semantics (single_choice) or keep
    contradictory labels consistent (multi_label).

    Returns:
        (parents_by_id, children_by_parent_id, standalone_metrics)

        ``parents_by_id`` maps parent UUID -> parent Metric row (fetched
        from the DB so the prompt builder has access to the parent's
        description and selection_mode).

        ``standalone_metrics`` is the leftover list of LLM metrics that
        have no parent — they are evaluated one-by-one (preserves the
        legacy code path so non-hierarchical metrics are unaffected).
    """

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
        # Drop groups whose parent disappeared (deleted mid-run) — the
        # children fall back to standalone evaluation so we don't lose
        # their scores entirely.
        orphaned: list[UUID] = []
        for pid in list(children_by_parent.keys()):
            if pid not in parents_by_id:
                orphaned.append(pid)
        for pid in orphaned:
            standalone.extend(children_by_parent.pop(pid))

    return parents_by_id, children_by_parent, standalone


def _rollup_parent(db, evaluation: CallImportEvaluation) -> None:
    rows = (
        db.query(CallImportEvaluationRow.status)
        .filter(CallImportEvaluationRow.evaluation_id == evaluation.id)
        .all()
    )
    total = len(rows)
    completed = sum(1 for (status,) in rows if status == "completed")
    failed = sum(1 for (status,) in rows if status == "failed")
    in_progress = sum(1 for (status,) in rows if status in {"pending", "running"})

    evaluation.total_rows = total
    evaluation.completed_rows = completed
    evaluation.failed_rows = failed

    if in_progress > 0:
        evaluation.status = "running"
        if not evaluation.started_at:
            evaluation.started_at = _now()
        return

    evaluation.finished_at = _now()
    if total == 0:
        evaluation.status = "completed"
    elif failed == 0:
        evaluation.status = "completed"
    elif completed == 0:
        evaluation.status = "failed"
    else:
        evaluation.status = "partial"


# Per-task time limits keep a wedged audio evaluation (e.g. torch.hub UTMOS
# download stuck on a network hiccup, or libgomp deadlock in a prefork child)
# from holding a worker child hostage for the global 30 min fallback. With
# task_acks_late + worker_max_tasks_per_child enabled in app/workers/config.py,
# a hard-killed task gets redelivered to a healthy child.
@celery_app.task(
    name="evaluate_call_import_row",
    bind=True,
    max_retries=2,
    time_limit=10 * 60,
    soft_time_limit=8 * 60,
)
def evaluate_call_import_row_task(self, eval_row_id: str):
    """Evaluate one row using the appropriate library per metric type."""
    db = SessionLocal()
    try:
        row_uuid = UUID(eval_row_id)
        eval_row = (
            db.query(CallImportEvaluationRow)
            .filter(CallImportEvaluationRow.id == row_uuid)
            .first()
        )
        if not eval_row:
            logger.warning("CallImportEvaluationRow {} not found", eval_row_id)
            return {"status": "skipped", "reason": "row_not_found"}

        evaluation = (
            db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == eval_row.evaluation_id)
            .first()
        )
        if not evaluation:
            logger.warning("CallImportEvaluation {} missing", eval_row.evaluation_id)
            eval_row.status = "failed"
            eval_row.error_message = "Evaluation parent not found"
            db.commit()
            return {"status": "failed", "reason": "evaluation_missing"}

        source_row = (
            db.query(CallImportRow)
            .filter(CallImportRow.id == eval_row.call_import_row_id)
            .first()
        )
        if not source_row:
            eval_row.status = "failed"
            eval_row.error_message = "Source call import row not found"
            eval_row.finished_at = _now()
            db.commit()
            _rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "source_row_missing"}

        eval_row.status = "running"
        eval_row.celery_task_id = self.request.id
        eval_row.error_message = None
        eval_row.started_at = eval_row.started_at or _now()
        if evaluation.status == "pending":
            evaluation.status = "running"
            evaluation.started_at = evaluation.started_at or _now()
        db.commit()

        transcript = (source_row.transcript or "").strip()
        recording_s3_key = (source_row.recording_s3_key or "").strip() or None
        has_audio = recording_s3_key is not None

        metric_ids_raw = evaluation.selected_metric_ids or []
        metric_ids = []
        for item in metric_ids_raw:
            try:
                metric_ids.append(UUID(str(item)))
            except (TypeError, ValueError):
                continue

        metrics = (
            db.query(Metric)
            .filter(
                Metric.organization_id == evaluation.organization_id,
                Metric.id.in_(metric_ids),
                Metric.enabled.is_(True),
            )
            .all()
            if metric_ids
            else []
        )
        if not metrics:
            eval_row.status = "failed"
            eval_row.error_message = "No enabled metrics selected for this evaluation"
            eval_row.finished_at = _now()
            db.commit()
            _rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "no_metrics"}

        llm_metrics, audio_metrics, metric_scores = _categorize_metrics(
            metrics, has_audio
        )

        if not llm_metrics and not audio_metrics:
            eval_row.status = "failed"
            eval_row.error_message = (
                "Selected metrics require audio but no recording is available "
                "for this row"
            )
            eval_row.metric_scores = _as_json_dict(metric_scores)
            eval_row.finished_at = _now()
            db.commit()
            _rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "audio_required"}

        if llm_metrics and not transcript:
            logger.warning(
                "[CallImportEval {}] Skipping LLM metrics: transcript is empty",
                eval_row.id,
            )
            err = RuntimeError("Transcript is empty for this row")
            metric_scores.update(handle_llm_evaluation_error(llm_metrics, err))
            eval_row.status = "failed"
            eval_row.error_message = (
                "Transcript is empty for this row; LLM-evaluated metrics "
                "could not be scored."
            )
            eval_row.metric_scores = _as_json_dict(metric_scores)
            eval_row.finished_at = _now()
            db.commit()
            _rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "missing_transcript"}

        result_id = f"call-import-eval:{eval_row.id}"
        evaluation_failed = False
        primary_error_message: str | None = None

        if audio_metrics and recording_s3_key:
            try:
                audio_scores = evaluate_audio_metrics(
                    audio_s3_key=recording_s3_key,
                    audio_metrics=audio_metrics,
                    result_id=result_id,
                )
                metric_scores.update(audio_scores)
            except Exception as audio_err:  # noqa: BLE001
                logger.exception(
                    "[CallImportEval {}] Audio analysis failed", eval_row.id
                )
                metric_scores.update(
                    handle_audio_evaluation_error(audio_metrics, audio_err)
                )

        if llm_metrics and transcript:
            ai_providers = (
                db.query(AIProvider)
                .filter(
                    AIProvider.organization_id == evaluation.organization_id,
                    AIProvider.is_active.is_(True),
                )
                .all()
            )

            # Split LLM metrics into "hierarchical groups" (children
            # sharing a parent) and "standalone" leaves. Each
            # hierarchical group is evaluated as one logical unit so
            # the LLM sees every sibling at once and the
            # single_choice/multi_label invariants can be enforced.
            parents_by_id, children_by_parent, standalone_metrics = (
                _build_parent_groups(db, llm_metrics)
            )

            # Group metrics by their effective (provider, model) so we
            # only call the LLM once per unique config. Per-metric
            # overrides win, then fall back to the run-level default,
            # then the historical OpenAI/gpt-4o default inside
            # ``evaluate_with_llm``.
            run_provider = (evaluation.llm_provider or "").strip() or None
            run_model = (evaluation.llm_model or "").strip() or None
            overrides = (
                evaluation.metric_llm_overrides
                if isinstance(evaluation.metric_llm_overrides, dict)
                else {}
            )

            def _resolve_pm(metric: Metric) -> tuple[str | None, str | None]:
                override = overrides.get(str(metric.id)) or {}
                provider = (
                    override.get("provider") or run_provider or None
                )
                model = override.get("model") or run_model or None
                return provider, model

            # Bucket = ((provider, model), parent_id_or_None) -> metrics.
            # parent_id_or_None keys hierarchical groups; ``None`` keys
            # the standalone bucket. Splitting on parent_id lets us pass
            # ``parent_metric`` to ``evaluate_with_llm`` for prompt rendering.
            BucketKey = tuple[tuple[str | None, str | None], UUID | None]
            groups: dict[BucketKey, list[Metric]] = {}
            for metric in standalone_metrics:
                provider, model = _resolve_pm(metric)
                groups.setdefault(((provider, model), None), []).append(metric)
            for parent_id, children in children_by_parent.items():
                # Children of the same parent MUST end up in one bucket
                # (no per-child provider/model split inside a hierarchy
                # group) — otherwise we lose the mutex / consistency
                # guarantees. Use the first child's resolved config.
                provider, model = _resolve_pm(children[0])
                groups.setdefault(
                    ((provider, model), parent_id), []
                ).extend(children)

            for (config, parent_id), bucket in groups.items():
                provider, model = config
                evaluator_obj = None
                if provider and model:
                    evaluator_obj = SimpleNamespace(
                        llm_provider=provider,
                        llm_model=model,
                        custom_prompt=None,
                    )
                parent_metric = (
                    parents_by_id.get(parent_id) if parent_id else None
                )
                try:
                    llm_scores, _eval_time = evaluate_with_llm(
                        transcription=transcript,
                        llm_metrics=bucket,
                        ai_providers=ai_providers,
                        organization_id=evaluation.organization_id,
                        result_id=result_id,
                        db=db,
                        evaluator=evaluator_obj,
                        agent=None,
                        persona=None,
                        scenario=None,
                        parent_metric=parent_metric,
                    )
                    metric_scores.update(llm_scores)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "[CallImportEval {}] LLM evaluation failed for "
                        "provider={} model={} parent={}",
                        eval_row.id,
                        provider,
                        model,
                        parent_id,
                    )
                    metric_scores.update(
                        handle_llm_evaluation_error(bucket, exc)
                    )
                    evaluation_failed = True
                    primary_error_message = str(exc)

        if evaluation_failed:
            eval_row.status = "failed"
            eval_row.error_message = (
                primary_error_message or "Evaluation failed for one or more metrics"
            )
        else:
            eval_row.status = "completed"
            eval_row.error_message = None

        eval_row.metric_scores = _as_json_dict(metric_scores)
        eval_row.finished_at = _now()
        db.commit()

        _rollup_parent(db, evaluation)
        db.commit()

        return {
            "status": eval_row.status,
            "eval_row_id": eval_row_id,
            "metrics": len(eval_row.metric_scores or {}),
        }
    finally:
        db.close()
