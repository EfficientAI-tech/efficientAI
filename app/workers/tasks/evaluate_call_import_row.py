"""Celery task: evaluate one CallImport row against selected metrics.

Metric routing mirrors ``process_evaluator_result``:

* Audio-only metrics run on the ``audio-metrics`` queue via
  :func:`app.workers.tasks.evaluate_call_import_row_audio.evaluate_call_import_row_audio_task`
  (``worker`` service). This task handles LLM / comparison metrics only.
* When chained after the audio phase, ``_skip_audio=True`` merges scores
  already persisted on the row.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, List, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.database import (
    AIProvider,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
)
from app.workers.config import celery_app
from app.workers.tasks.evaluate_call_import_row_core import (
    as_json_dict,
    build_all_columns_block,
    build_llm_config_buckets,
    bucket_needs_comparison_pair,
    build_parent_groups,
    categorize_metrics,
    load_enabled_metrics,
    metric_text_references_production,
    now_utc,
    parse_restricted_metric_uuids,
    rollup_parent,
    commit_terminal_row_and_rollup,
    was_cancelled_externally,
)
from app.workers.tasks.helpers.llm_evaluation import (
    evaluate_with_llm,
    flatten_metric_groups,
    handle_llm_evaluation_error,
)

# Re-export core helpers for tests and API route mirrors.
_now = now_utc
_as_json_dict = as_json_dict
_was_cancelled_externally = was_cancelled_externally
_build_all_columns_block = build_all_columns_block
_categorize_metrics = categorize_metrics
_rollup_parent = rollup_parent
_metric_text_references_production = metric_text_references_production


_commit_terminal_row_and_rollup = commit_terminal_row_and_rollup


def _rollup_terminal(
    row_db: Session,
    catalog_db,
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    *,
    previous_row_status: str,
) -> None:
    cat = catalog_db if catalog_db is not row_db else None
    _commit_terminal_row_and_rollup(
        row_db,
        evaluation,
        eval_row,
        previous_row_status=previous_row_status,
        catalog_db=cat,
    )


def _persist_eval_sessions(row_db, catalog_db) -> None:
    row_db.commit()
    if catalog_db is not row_db:
        catalog_db.commit()


def _run_llm_scoring(
    *,
    eval_row_id: UUID,
    organization_id: UUID,
    transcript: str,
    production_transcript: str,
    diarised_transcript: str,
    llm_config_buckets: dict,
    comparison_metric_ids: set[str],
    all_columns_block: str | None,
    ai_providers: list,
    llm_provider: str | None,
    llm_model: str | None,
    llm_credential_id: str | None,
    llm_config: dict | None,
    discover_new_metrics: bool,
    running_discovered_metrics: list,
    transcript_unavailable: bool,
    missing_label: str,
) -> dict[str, Any]:
    """Score LLM metrics without holding a long-lived DB session."""
    result_id = f"call-import-eval:{eval_row_id}"
    metric_scores: dict[str, dict[str, Any]] = {}
    evaluation_failed = transcript_unavailable
    primary_error_message: str | None = (
        f"No {missing_label} transcript for this row; transcript-based "
        "metrics could not be scored."
        if transcript_unavailable
        else None
    )

    if not llm_config_buckets:
        return {
            "metric_scores": metric_scores,
            "evaluation_failed": evaluation_failed,
            "primary_error_message": primary_error_message,
        }

    metric_discovery_emitted = False

    for config, groups in llm_config_buckets.items():
        provider, model, llm_config_key, credential_id = config
        llm_cfg = json.loads(llm_config_key) if llm_config_key else None
        evaluator_obj = None
        if provider and model:
            evaluator_obj = SimpleNamespace(
                llm_provider=provider,
                llm_model=model,
                llm_config=llm_cfg,
                llm_credential_id=credential_id,
                custom_prompt=None,
            )
        bucket_metrics = flatten_metric_groups(groups)
        emit_metric_discovery = discover_new_metrics and not metric_discovery_emitted
        bucket_comparison_pair: tuple[str, str] | None = None
        if bucket_needs_comparison_pair(
            groups,
            production_transcript=production_transcript,
            diarised_transcript=diarised_transcript,
            comparison_metric_ids=comparison_metric_ids,
        ):
            bucket_comparison_pair = (
                production_transcript,
                diarised_transcript,
            )
        bucket_has_transcript_metrics = any(
            str(metric.id) not in comparison_metric_ids for metric in bucket_metrics
        )
        bucket_transcription = (
            transcript if bucket_has_transcript_metrics else ""
        )
        try:
            llm_db = SessionLocal()
            try:
                llm_scores, _eval_time = evaluate_with_llm(
                    transcription=bucket_transcription,
                    llm_metrics=bucket_metrics,
                    ai_providers=ai_providers,
                    organization_id=organization_id,
                    result_id=result_id,
                    db=llm_db,
                    evaluator=evaluator_obj,
                    agent=None,
                    persona=None,
                    scenario=None,
                    all_columns_block=all_columns_block,
                    comparison_pair=bucket_comparison_pair,
                    discover_new_metrics=emit_metric_discovery,
                    running_discovered_metrics=(
                        running_discovered_metrics
                        if emit_metric_discovery
                        else None
                    ),
                    metric_groups=groups,
                )
            finally:
                llm_db.close()
            if emit_metric_discovery:
                metric_discovery_emitted = True
            metric_scores.update(llm_scores)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[CallImportEval {}] LLM evaluation failed for "
                "provider={} model={}",
                eval_row_id,
                provider,
                model,
            )
            metric_scores.update(handle_llm_evaluation_error(bucket_metrics, exc))
            evaluation_failed = True
            primary_error_message = str(exc)

    return {
        "metric_scores": metric_scores,
        "evaluation_failed": evaluation_failed,
        "primary_error_message": primary_error_message,
    }


# Per-task time limits keep a wedged LLM evaluation from holding a worker
# child hostage for the global 30 min fallback.
@celery_app.task(
    name="evaluate_call_import_row",
    bind=True,
    max_retries=2,
    time_limit=10 * 60,
    soft_time_limit=8 * 60,
)
def evaluate_call_import_row_task(
    self,
    eval_row_id: str,
    restricted_metric_ids: Optional[List[str]] = None,
    _eval_slot_task_id: Optional[str] = None,
    _skip_audio: bool = False,
):
    """Evaluate one row using the appropriate library per metric type.

    When ``restricted_metric_ids`` is set, this is a **metric-subset**
    pass: only those metrics are recomputed, and the resulting scores
    are merged into the row's existing ``metric_scores`` dict so other
    metrics' previously-computed values are preserved. Used by the
    "Re-run metrics" UI; the create-evaluation flow always leaves this
    None for a full row evaluation.
    """
    slot_task_id = _eval_slot_task_id or self.request.id
    scoring_inputs: dict[str, Any] | None = None
    restricted_metric_uuids: list[UUID] | None = None
    usage_ctx_token = None
    try:
        from app.db_sharding.row_ops import (
            close_row_sessions,
            locate_call_import_evaluation_row,
        )

        row_db = catalog_db = None
        try:
            row_uuid = UUID(eval_row_id)
            try:
                row_db, catalog_db, eval_row, source_row, _shard_id = (
                    locate_call_import_evaluation_row(row_uuid)
                )
            except LookupError:
                logger.warning("CallImportEvaluationRow {} not found", eval_row_id)
                return {"status": "skipped", "reason": "row_not_found"}

            evaluation = (
                catalog_db.query(CallImportEvaluation)
                .filter(CallImportEvaluation.id == eval_row.evaluation_id)
                .first()
            )
            if not evaluation:
                logger.warning(
                    "CallImportEvaluation {} missing", eval_row.evaluation_id
                )
                eval_row.status = "failed"
                eval_row.error_message = "Evaluation parent not found"
                row_db.commit()
                return {"status": "failed", "reason": "evaluation_missing"}

            from app.services.usage.call_import_context import (
                call_import_evaluation_usage_context,
            )
            from app.services.usage.context import set_usage_context

            usage_ctx_token = set_usage_context(
                call_import_evaluation_usage_context(
                    organization_id=evaluation.organization_id,
                    workspace_id=evaluation.workspace_id,
                    evaluation_id=evaluation.id,
                    call_import_id=evaluation.call_import_id,
                )
            )

            previous_row_status = eval_row.status

            eval_row.status = "running"
            eval_row.celery_task_id = self.request.id
            eval_row.error_message = None
            eval_row.started_at = eval_row.started_at or _now()
            if evaluation.status == "pending":
                evaluation.status = "running"
                evaluation.started_at = evaluation.started_at or _now()
            _persist_eval_sessions(row_db, catalog_db)
            previous_row_status = "running"

            production_transcript = (source_row.transcript or "").strip()
            diarised_transcript = (source_row.diarised_transcript or "").strip()
            eval_source = (
                (evaluation.transcript_source or "diarised").strip().lower()
            )
            if eval_source == "production":
                transcript = production_transcript
                missing_label = "production"
            else:
                transcript = diarised_transcript
                missing_label = "diarised"
            recording_s3_key = (source_row.recording_s3_key or "").strip() or None
            has_audio = recording_s3_key is not None

            restricted_metric_uuids = parse_restricted_metric_uuids(
                restricted_metric_ids
            )
            if (
                restricted_metric_ids is not None
                and restricted_metric_uuids is not None
            ):
                selected_raw = {
                    str(x) for x in (evaluation.selected_metric_ids or [])
                }
                if restricted_metric_uuids and not any(
                    str(mid) in selected_raw for mid in restricted_metric_uuids
                ):
                    eval_row.status = "completed"
                    eval_row.error_message = None
                    eval_row.finished_at = _now()
                    _rollup_terminal(
                        row_db,
                        catalog_db,
                        evaluation,
                        eval_row,
                        previous_row_status=previous_row_status,
                    )
                    return {
                        "status": "skipped",
                        "reason": "restricted_metric_ids_no_match",
                    }

            metrics = load_enabled_metrics(
                catalog_db, evaluation, restricted_metric_ids=restricted_metric_ids
            )
            if not metrics:
                eval_row.status = "failed"
                eval_row.error_message = (
                    "No enabled metrics selected for this evaluation"
                )
                eval_row.finished_at = _now()
                _rollup_terminal(
                    row_db,
                    catalog_db,
                    evaluation,
                    eval_row,
                    previous_row_status=previous_row_status,
                )
                return {"status": "failed", "reason": "no_metrics"}

            raw_columns = (
                source_row.raw_columns
                if isinstance(source_row.raw_columns, dict)
                else {}
            )
            parent_import = getattr(source_row, "call_import", None)
            if parent_import is None and source_row.call_import_id:
                from app.models.database import CallImport

                parent_import = (
                    catalog_db.query(CallImport)
                    .filter(CallImport.id == source_row.call_import_id)
                    .first()
                )
            custom_column_mapping = (
                parent_import.custom_column_mapping
                if parent_import is not None
                and isinstance(
                    getattr(parent_import, "custom_column_mapping", None), dict
                )
                else {}
            )

            (
                transcript_metrics,
                audio_metrics,
                comparison_metrics,
                metric_scores,
            ) = _categorize_metrics(
                metrics,
                has_audio,
                has_production_transcript=bool(production_transcript),
                has_diarised_transcript=bool(diarised_transcript),
            )

            if _skip_audio:
                existing_scores = (
                    eval_row.metric_scores
                    if isinstance(eval_row.metric_scores, dict)
                    else {}
                )
                metric_scores = {**existing_scores, **metric_scores}
                audio_metrics = []
            elif audio_metrics:
                logger.warning(
                    "[CallImportEval {}] Audio metrics present but task was "
                    "dispatched without audio phase — skipping audio bucket",
                    eval_row.id,
                )
                audio_metrics = []

            all_columns_block = _build_all_columns_block(
                raw_columns, custom_column_mapping
            )

            if (
                not transcript_metrics
                and not audio_metrics
                and not comparison_metrics
            ):
                eval_row.status = "failed"
                eval_row.error_message = (
                    "Selected metrics could not be evaluated on this row "
                    "(missing audio, missing one of the two transcripts "
                    "required for a comparison metric, or no enabled "
                    "metrics matched)."
                )
                eval_row.metric_scores = _as_json_dict(metric_scores)
                eval_row.finished_at = _now()
                _rollup_terminal(
                    row_db,
                    catalog_db,
                    evaluation,
                    eval_row,
                    previous_row_status=previous_row_status,
                )
                return {"status": "failed", "reason": "no_evaluable_metrics"}

            transcript_unavailable = bool(transcript_metrics) and not transcript
            if (
                transcript_unavailable
                and not audio_metrics
                and not comparison_metrics
            ):
                logger.warning(
                    "[CallImportEval {}] Skipping LLM metrics: {} transcript "
                    "is empty",
                    eval_row.id,
                    missing_label,
                )
                empty_msg = f"No {missing_label} transcript for this row"
                err = RuntimeError(empty_msg)
                metric_scores.update(
                    handle_llm_evaluation_error(transcript_metrics, err)
                )
                eval_row.status = "failed"
                eval_row.error_message = (
                    f"{empty_msg}; LLM-evaluated metrics could not be scored."
                )
                eval_row.metric_scores = _as_json_dict(metric_scores)
                eval_row.finished_at = _now()
                _rollup_terminal(
                    row_db,
                    catalog_db,
                    evaluation,
                    eval_row,
                    previous_row_status=previous_row_status,
                )
                return {"status": "failed", "reason": "missing_transcript"}

            if transcript_unavailable:
                logger.warning(
                    "[CallImportEval {}] Skipping transcript-LLM metrics: {} "
                    "transcript is empty (audio/column metrics still scored)",
                    eval_row.id,
                    missing_label,
                )
                empty_msg = f"No {missing_label} transcript for this row"
                err = RuntimeError(empty_msg)
                metric_scores.update(
                    handle_llm_evaluation_error(transcript_metrics, err)
                )
                transcript_metrics = []

            ai_providers = (
                catalog_db.query(AIProvider)
                .filter(
                    AIProvider.organization_id == evaluation.organization_id,
                    AIProvider.is_active.is_(True),
                )
                .all()
            )

            running_discovered_metrics: list = []
            running_discovered_by_parent: dict[UUID, list] = {}
            llm_metrics_for_scoring: list[Metric] = list(comparison_metrics)
            if transcript:
                llm_metrics_for_scoring = transcript_metrics + comparison_metrics

            llm_config_buckets: dict = {}
            comparison_metric_ids = {str(m.id) for m in comparison_metrics}
            if llm_metrics_for_scoring:
                if bool(getattr(evaluation, "discover_new_metrics", False)):
                    from app.api.v1.routes.call_import_evaluations import (
                        _get_running_discovered_metrics,
                    )

                    alias_map_metrics = (
                        evaluation.discovered_metric_aliases
                        if isinstance(evaluation.discovered_metric_aliases, dict)
                        else {}
                    )
                    running_discovered_metrics = _get_running_discovered_metrics(
                        catalog_db,
                        evaluation.id,
                        organization_id=evaluation.organization_id,
                        alias_map=alias_map_metrics,
                    )
                from app.api.v1.routes.call_import_evaluations import (
                    _alias_map_for_parent,
                    _get_running_discovered_labels,
                )

                parents_by_id, children_by_parent, _ = build_parent_groups(
                    catalog_db, llm_metrics_for_scoring
                )
                for parent_id in children_by_parent:
                    parent_metric = parents_by_id.get(parent_id)
                    if parent_metric is None:
                        continue
                    if not bool(getattr(parent_metric, "allow_discovery", False)):
                        continue
                    if (parent_metric.selection_mode or "").lower() not in {
                        "single_choice",
                        "multi_label",
                    }:
                        continue
                    running_discovered_by_parent[parent_id] = (
                        _get_running_discovered_labels(
                            catalog_db,
                            evaluation.id,
                            parent_metric.id,
                            organization_id=evaluation.organization_id,
                            alias_map=_alias_map_for_parent(
                                evaluation, parent_metric.id
                            ),
                        )
                    )

                overrides = (
                    evaluation.metric_llm_overrides
                    if isinstance(evaluation.metric_llm_overrides, dict)
                    else {}
                )
                llm_config_buckets = build_llm_config_buckets(
                    catalog_db,
                    llm_metrics_for_scoring,
                    overrides=overrides,
                    run_provider=(evaluation.llm_provider or "").strip() or None,
                    run_model=(evaluation.llm_model or "").strip() or None,
                    run_llm_config=(
                        evaluation.llm_config
                        if isinstance(evaluation.llm_config, dict)
                        else None
                    ),
                    run_credential_id=(
                        str(evaluation.llm_credential_id)
                        if evaluation.llm_credential_id
                        else None
                    ),
                    running_discovered_by_parent=running_discovered_by_parent,
                )

            scoring_inputs = {
                "eval_row_id": eval_row.id,
                "organization_id": evaluation.organization_id,
                "transcript": transcript,
                "production_transcript": production_transcript,
                "diarised_transcript": diarised_transcript,
                "llm_config_buckets": llm_config_buckets,
                "comparison_metric_ids": comparison_metric_ids,
                "all_columns_block": all_columns_block,
                "ai_providers": ai_providers,
                "llm_provider": evaluation.llm_provider,
                "llm_model": evaluation.llm_model,
                "llm_credential_id": (
                    str(evaluation.llm_credential_id)
                    if evaluation.llm_credential_id
                    else None
                ),
                "llm_config": evaluation.llm_config,
                "discover_new_metrics": bool(
                    getattr(evaluation, "discover_new_metrics", False)
                ),
                "running_discovered_metrics": running_discovered_metrics,
                "transcript_unavailable": transcript_unavailable,
                "missing_label": missing_label,
                "pre_llm_metric_scores": dict(metric_scores),
            }
        finally:
            if row_db is not None:
                close_row_sessions(row_db, catalog_db)

        pre_llm_metric_scores = scoring_inputs.pop("pre_llm_metric_scores")
        llm_result = _run_llm_scoring(**scoring_inputs)
        metric_scores = {
            **pre_llm_metric_scores,
            **llm_result["metric_scores"],
        }
        evaluation_failed = llm_result["evaluation_failed"]
        primary_error_message = llm_result["primary_error_message"]

        row_db = catalog_db = None
        try:
            from app.db_sharding.row_ops import (
                close_row_sessions,
                locate_call_import_evaluation_row,
            )

            try:
                row_db, catalog_db, eval_row, _source_row, _ = (
                    locate_call_import_evaluation_row(UUID(eval_row_id))
                )
            except LookupError:
                logger.warning(
                    "[CallImportEval {}] Row not found on any shard — skipping",
                    eval_row_id,
                )
                return {"status": "skipped", "reason": "row_not_found"}
            evaluation = (
                catalog_db.query(CallImportEvaluation)
                .filter(CallImportEvaluation.id == eval_row.evaluation_id)
                .first()
            )
            if not evaluation:
                return {"status": "failed", "reason": "evaluation_missing"}

            if _was_cancelled_externally(row_db, eval_row):
                logger.info(
                    "[CallImportEval {}] Skipping terminal write; "
                    "row was cancelled by user",
                    eval_row.id,
                )
                try:
                    _rollup_parent(
                        catalog_db,
                        evaluation,
                        previous_row_status="running",
                        new_row_status="failed",
                    )
                    catalog_db.commit()
                except Exception:  # noqa: BLE001 — rollup is best-effort here
                    catalog_db.rollback()
                return {
                    "status": "cancelled",
                    "eval_row_id": eval_row_id,
                }

            if evaluation_failed:
                eval_row.status = "failed"
                eval_row.error_message = (
                    primary_error_message
                    or "Evaluation failed for one or more metrics"
                )
            else:
                eval_row.status = "completed"
                eval_row.error_message = None

            from app.api.v1.routes.call_import_evaluations import (
                normalize_scores_with_aliases,
            )

            normalize_scores_with_aliases(
                metric_scores, evaluation, catalog_db, evaluation.organization_id
            )

            new_scores = _as_json_dict(metric_scores)
            if restricted_metric_uuids:
                existing = (
                    eval_row.metric_scores
                    if isinstance(eval_row.metric_scores, dict)
                    else {}
                )
                merged = dict(existing)
                for key, value in new_scores.items():
                    merged[key] = value
                eval_row.metric_scores = merged
            else:
                eval_row.metric_scores = new_scores
            eval_row.finished_at = _now()
            _rollup_terminal(
                row_db,
                catalog_db,
                evaluation,
                eval_row,
                previous_row_status="running",
            )

            return {
                "status": eval_row.status,
                "eval_row_id": eval_row_id,
                "metrics": len(eval_row.metric_scores or {}),
                "subset_retry": bool(restricted_metric_uuids),
            }
        finally:
            if row_db is not None:
                close_row_sessions(row_db, catalog_db)
    finally:
        if usage_ctx_token is not None:
            from app.services.usage.context import reset_usage_context

            reset_usage_context(usage_ctx_token)
        from app.workers.concurrency.fair_dispatch import (
            finish_eval_work_and_redispatch,
        )

        finish_eval_work_and_redispatch(
            slot_task_id,
            restricted_metric_ids=restricted_metric_ids,
        )
