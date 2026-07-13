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
    build_parent_groups,
    categorize_metrics,
    load_enabled_metrics,
    metric_text_references_production,
    now_utc,
    parse_restricted_metric_uuids,
    rollup_parent,
    was_cancelled_externally,
)
from app.workers.tasks.helpers.llm_evaluation import (
    evaluate_with_llm,
    handle_llm_evaluation_error,
)

# Re-export core helpers for tests and API route mirrors.
_now = now_utc
_as_json_dict = as_json_dict
_was_cancelled_externally = was_cancelled_externally
_build_all_columns_block = build_all_columns_block
_categorize_metrics = categorize_metrics
_build_parent_groups = build_parent_groups
_rollup_parent = rollup_parent
_metric_text_references_production = metric_text_references_production


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
    db = SessionLocal()
    evaluation_id_for_dispatch: Optional[str] = None
    slot_task_id = _eval_slot_task_id or self.request.id
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

        evaluation_id_for_dispatch = str(evaluation.id)

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

        production_transcript = (source_row.transcript or "").strip()
        diarised_transcript = (source_row.diarised_transcript or "").strip()
        transcript = diarised_transcript
        missing_label = "diarised"
        recording_s3_key = (source_row.recording_s3_key or "").strip() or None
        has_audio = recording_s3_key is not None

        restricted_metric_uuids = parse_restricted_metric_uuids(
            restricted_metric_ids
        )
        if restricted_metric_ids is not None and restricted_metric_uuids is not None:
            selected_raw = {str(x) for x in (evaluation.selected_metric_ids or [])}
            if restricted_metric_uuids and not any(
                str(mid) in selected_raw for mid in restricted_metric_uuids
            ):
                eval_row.status = "completed"
                eval_row.error_message = None
                eval_row.finished_at = _now()
                db.commit()
                _rollup_parent(db, evaluation)
                db.commit()
                return {
                    "status": "skipped",
                    "reason": "restricted_metric_ids_no_match",
                }

        metrics = load_enabled_metrics(
            db, evaluation, restricted_metric_ids=restricted_metric_ids
        )
        if not metrics:
            eval_row.status = "failed"
            eval_row.error_message = "No enabled metrics selected for this evaluation"
            eval_row.finished_at = _now()
            db.commit()
            _rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "no_metrics"}

        raw_columns = (
            source_row.raw_columns
            if isinstance(source_row.raw_columns, dict)
            else {}
        )

        # Surface the parent import's friendly-name → CSV-header
        # dictionary so column-input metrics that stored a friendly
        # name can still resolve to the right ``raw_columns`` cell.
        # Loaded via the relationship so we avoid an extra query when
        # SQLAlchemy already has the parent in the identity map.
        parent_import = getattr(source_row, "call_import", None)
        custom_column_mapping = (
            parent_import.custom_column_mapping
            if parent_import is not None
            and isinstance(getattr(parent_import, "custom_column_mapping", None), dict)
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
            db.commit()
            _rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "no_evaluable_metrics"}

        # Transcript-based LLM metrics still need a transcript. When
        # the run has nothing else to score (no audio, no comparison
        # metrics) and the transcript is empty we keep the legacy
        # hard-fail signature so callers who key off
        # ``result["reason"] == "missing_transcript"`` continue to
        # work. When the row also has audio / comparison metrics we
        # soft-fail just the transcript bucket so those still produce
        # real scores instead of being held hostage by a missing
        # transcript.
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
            db.commit()
            _rollup_parent(db, evaluation)
            db.commit()
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

        result_id = f"call-import-eval:{eval_row.id}"
        evaluation_failed = transcript_unavailable
        primary_error_message: str | None = (
            f"No {missing_label} transcript for this row; transcript-based "
            "metrics could not be scored."
            if transcript_unavailable
            else None
        )

        ai_providers_cache: list | None = None

        def _load_ai_providers() -> list:
            nonlocal ai_providers_cache
            if ai_providers_cache is None:
                ai_providers_cache = (
                    db.query(AIProvider)
                    .filter(
                        AIProvider.organization_id == evaluation.organization_id,
                        AIProvider.is_active.is_(True),
                    )
                    .all()
                )
            return ai_providers_cache

        if comparison_metrics:
            run_provider = (evaluation.llm_provider or "").strip() or None
            run_model = (evaluation.llm_model or "").strip() or None
            run_llm_config = (
                evaluation.llm_config
                if isinstance(getattr(evaluation, "llm_config", None), dict)
                else None
            )
            overrides = (
                evaluation.metric_llm_overrides
                if isinstance(evaluation.metric_llm_overrides, dict)
                else {}
            )
            for cmp_metric in comparison_metrics:
                override = overrides.get(str(cmp_metric.id)) or {}
                provider = override.get("provider") or run_provider or None
                model = override.get("model") or run_model or None
                llm_config = override.get("llm_config") or run_llm_config
                evaluator_obj = None
                if provider and model:
                    evaluator_obj = SimpleNamespace(
                        llm_provider=provider,
                        llm_model=model,
                        llm_config=llm_config,
                        custom_prompt=None,
                    )
                try:
                    cmp_scores, _eval_time = evaluate_with_llm(
                        transcription="",
                        llm_metrics=[cmp_metric],
                        ai_providers=_load_ai_providers(),
                        organization_id=evaluation.organization_id,
                        result_id=result_id,
                        db=db,
                        evaluator=evaluator_obj,
                        agent=None,
                        persona=None,
                        scenario=None,
                        parent_metric=None,
                        running_discovered=None,
                        all_columns_block=all_columns_block,
                        comparison_pair=(
                            production_transcript,
                            diarised_transcript,
                        ),
                    )
                    metric_scores.update(cmp_scores)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "[CallImportEval {}] Transcript-compare LLM "
                        "evaluation failed for metric={} provider={} model={}",
                        eval_row.id,
                        cmp_metric.id,
                        provider,
                        model,
                    )
                    metric_scores.update(
                        handle_llm_evaluation_error([cmp_metric], exc)
                    )
                    evaluation_failed = True
                    primary_error_message = (
                        primary_error_message or str(exc)
                    )

        if transcript_metrics and transcript:
            llm_metrics = transcript_metrics
            ai_providers = _load_ai_providers()

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
            run_llm_config = (
                evaluation.llm_config
                if isinstance(getattr(evaluation, "llm_config", None), dict)
                else None
            )
            overrides = (
                evaluation.metric_llm_overrides
                if isinstance(evaluation.metric_llm_overrides, dict)
                else {}
            )

            def _llm_config_key(cfg: dict | None) -> str | None:
                if not cfg:
                    return None
                return json.dumps(cfg, sort_keys=True, default=str)

            def _resolve_pm(
                metric: Metric,
            ) -> tuple[str | None, str | None, dict | None]:
                override = overrides.get(str(metric.id)) or {}
                provider = (
                    override.get("provider") or run_provider or None
                )
                model = override.get("model") or run_model or None
                llm_config = override.get("llm_config") or run_llm_config
                return provider, model, llm_config

            # Bucket = ((provider, model, llm_config_key), parent_id_or_None) -> metrics.
            BucketKey = tuple[tuple[str | None, str | None, str | None], UUID | None]
            groups: dict[BucketKey, list[Metric]] = {}
            for metric in standalone_metrics:
                provider, model, llm_config = _resolve_pm(metric)
                groups.setdefault(
                    ((provider, model, _llm_config_key(llm_config)), None),
                    [],
                ).append(metric)
            for parent_id, children in children_by_parent.items():
                provider, model, llm_config = _resolve_pm(children[0])
                groups.setdefault(
                    ((provider, model, _llm_config_key(llm_config)), parent_id),
                    [],
                ).extend(children)

            # Top-level metric discovery is opt-in per evaluation. When
            # enabled, we feed the LLM the running list of candidates
            # already proposed earlier in this evaluation (post-merge /
            # post-deletion) so the model reuses keys instead of
            # re-inventing near-duplicates. We only want to issue the
            # discovery instruction ONCE per row even when the
            # selected metrics span multiple LLM-config buckets — pay
            # for the extra prompt block on the first call only.
            metric_discovery_enabled = bool(
                getattr(evaluation, "discover_new_metrics", False)
            )
            running_discovered_metrics: list = []
            if metric_discovery_enabled:
                from app.api.v1.routes.call_import_evaluations import (
                    _get_running_discovered_metrics,
                )

                alias_map_metrics = (
                    evaluation.discovered_metric_aliases
                    if isinstance(
                        evaluation.discovered_metric_aliases, dict
                    )
                    else {}
                )
                running_discovered_metrics = (
                    _get_running_discovered_metrics(
                        db,
                        evaluation.id,
                        organization_id=evaluation.organization_id,
                        alias_map=alias_map_metrics,
                    )
                )
            metric_discovery_emitted = False

            for (config, parent_id), bucket in groups.items():
                provider, model, llm_config_key = config
                llm_config = json.loads(llm_config_key) if llm_config_key else None
                evaluator_obj = None
                if provider and model:
                    evaluator_obj = SimpleNamespace(
                        llm_provider=provider,
                        llm_model=model,
                        llm_config=llm_config,
                        custom_prompt=None,
                    )
                parent_metric = (
                    parents_by_id.get(parent_id) if parent_id else None
                )
                # Pull the running discovered-label list for this parent
                # right before the LLM call so the prompt can ask the
                # model to REUSE existing keys instead of inventing
                # near-duplicates. Cheap query (one SELECT scoped to the
                # current evaluation_id). Imported inside the loop to
                # avoid a top-level import cycle between routes and
                # workers.
                running_discovered: list = []
                if (
                    parent_metric is not None
                    and bool(getattr(parent_metric, "allow_discovery", False))
                    and (parent_metric.selection_mode or "").lower()
                    in {"single_choice", "multi_label"}
                ):
                    from app.api.v1.routes.call_import_evaluations import (
                        _alias_map_for_parent,
                        _get_running_discovered_labels,
                    )

                    # Feed the LLM the post-merge / post-promotion view
                    # of running discoveries so it stops re-suggesting
                    # candidates the user has already curated. Without
                    # passing the org id + alias map, the prompt would
                    # still echo merged-out slugs and confuse the
                    # model.
                    running_discovered = _get_running_discovered_labels(
                        db,
                        evaluation.id,
                        parent_metric.id,
                        organization_id=evaluation.organization_id,
                        alias_map=_alias_map_for_parent(
                            evaluation, parent_metric.id
                        ),
                    )

                # Only ask the LLM for net-new top-level metric
                # candidates on the first bucket we process — keeps
                # the per-row token cost bounded when the user has
                # selected metrics spanning multiple provider/model or
                # parent buckets.
                emit_metric_discovery = (
                    metric_discovery_enabled
                    and not metric_discovery_emitted
                )

                # Auto-detect categorisation / standalone groups whose
                # prompt asks the LLM to read both transcripts. The
                # standalone case is already handled in
                # ``_categorize_metrics`` (those metrics never reach the
                # transcript bucket); this branch handles parent-grouped
                # metrics — if the parent OR any child describes the
                # production vs diarised pair, we pass ``comparison_pair``
                # alongside ``parent_metric`` so the prompt builder
                # emits the labeled pair AND the category block. We
                # only enable this when BOTH transcripts are actually
                # available on the row; otherwise fall back to the
                # standard single-transcript prompt (the LLM still has
                # ``all_columns_block`` for the raw production text).
                bucket_comparison_pair: tuple[str, str] | None = None
                if (
                    production_transcript
                    and diarised_transcript
                    and (
                        (
                            parent_metric is not None
                            and _metric_text_references_production(parent_metric)
                        )
                        or any(
                            _metric_text_references_production(m, parent=parent_metric)
                            for m in bucket
                        )
                    )
                ):
                    bucket_comparison_pair = (
                        production_transcript,
                        diarised_transcript,
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
                        running_discovered=running_discovered,
                        all_columns_block=all_columns_block,
                        comparison_pair=bucket_comparison_pair,
                        discover_new_metrics=emit_metric_discovery,
                        running_discovered_metrics=(
                            running_discovered_metrics
                            if emit_metric_discovery
                            else None
                        ),
                    )
                    if emit_metric_discovery:
                        metric_discovery_emitted = True
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

        # Cancelled-mid-flight guard: if the API flipped this row to the
        # cancelled sentinel while we were running the LLM / audio calls,
        # DON'T overwrite the cancelled state with our own terminal
        # status / score writes — the operator's cancel wins the race.
        # We still update the parent rollup so its counters reflect
        # the cancelled row before we exit.
        if _was_cancelled_externally(db, eval_row):
            logger.info(
                "[CallImportEval {}] Skipping terminal write; "
                "row was cancelled by user",
                eval_row.id,
            )
            try:
                _rollup_parent(db, evaluation)
                db.commit()
            except Exception:  # noqa: BLE001 — rollup is best-effort here
                db.rollback()
            return {
                "status": "cancelled",
                "eval_row_id": eval_row_id,
            }

        if evaluation_failed:
            eval_row.status = "failed"
            eval_row.error_message = (
                primary_error_message or "Evaluation failed for one or more metrics"
            )
        else:
            eval_row.status = "completed"
            eval_row.error_message = None

        # Honor any user-driven label merges + promotions that landed
        # while this row was being scored. Done as a single in-place
        # rewrite so the on-disk JSON for this row never contains a
        # slug the user has explicitly retired.
        from app.api.v1.routes.call_import_evaluations import (
            normalize_scores_with_aliases,
        )

        normalize_scores_with_aliases(
            metric_scores, evaluation, db, evaluation.organization_id
        )

        new_scores = _as_json_dict(metric_scores)
        if restricted_metric_uuids:
            # Metric-subset retry: merge the newly-computed scores
            # into whatever was already on the row so the metrics the
            # user didn't pick keep their prior values byte-identical.
            # We compare keys case-insensitively to handle the rare
            # case where the persisted dict mixes UUID-string casings.
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
        db.commit()

        _rollup_parent(db, evaluation)
        db.commit()

        return {
            "status": eval_row.status,
            "eval_row_id": eval_row_id,
            "metrics": len(eval_row.metric_scores or {}),
            "subset_retry": bool(restricted_metric_uuids),
        }
    finally:
        db.close()
        from app.workers.concurrency.fair_dispatch import (
            finish_eval_work_and_redispatch,
        )

        finish_eval_work_and_redispatch(
            slot_task_id,
            restricted_metric_ids=restricted_metric_ids,
        )
