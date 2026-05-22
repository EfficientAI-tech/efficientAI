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


_ALL_COLUMNS_BLOCK_MAX_CHARS = 16_000
_ALL_COLUMNS_CELL_MAX_CHARS = 4_000


# Phrases that, when present in a metric's (or its parent's)
# description, mean "the LLM is expected to read BOTH the production
# and diarised transcripts when scoring this metric". Detection is
# case-insensitive and substring-based — we err on the side of
# triggering comparison mode (false positives just give the LLM extra
# context, which the prompt explicitly tells it is supporting context).
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


def _metric_text_references_production(
    metric: Metric, parent: Metric | None = None
) -> bool:
    """Return True when the metric (or its parent) wants both transcripts.

    Scans the metric's ``description`` for one of the well-known phrases
    above. When ``parent`` is provided (the metric is part of a
    categorisation group) the parent's description is checked too — if
    the parent says "compare the two transcripts and pick a label", we
    want EVERY child in the group to receive the production / diarised
    pair, not just the children that happen to repeat the phrase.

    This is the auto-detection counterpart to
    ``Metric.compare_transcripts`` (the explicit boolean flag). Both
    paths route through the same prompt-builder ``comparison_pair``
    arg downstream so the LLM sees the same shape either way.
    """
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


def _build_all_columns_block(
    raw_columns: dict[str, Any] | None,
    custom_column_mapping: dict[str, Any] | None = None,
) -> str | None:
    """Render EVERY non-empty cell from ``raw_columns`` as a labelled block.

    Returns ``None`` when there is nothing to render (no raw columns, or
    every cell is empty) so the prompt builder can skip the "Imported
    Columns" section entirely.

    Cells are emitted in the order they appear in ``raw_columns`` (which
    is preserved by Postgres JSONB iteration). When a friendly-name
    mapping is provided via ``CallImport.custom_column_mapping`` we also
    surface the friendly name alongside the original CSV header so the
    LLM can reason about either identifier the metric description might
    reference.

    Per-cell text is capped at 4 KB and the whole block at 16 KB — wide
    CSVs with multi-MB cells would otherwise blow the model's context
    window in a single line.
    """
    if not isinstance(raw_columns, dict) or not raw_columns:
        return None

    mapping = (
        custom_column_mapping
        if isinstance(custom_column_mapping, dict)
        else {}
    )
    # Reverse map: CSV header -> friendly name (for showing the friendly
    # name alongside the CSV header when the user configured one).
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


def _categorize_metrics(
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
    """Split selected metrics into transcript-LLM, audio, and
    transcript-compare buckets.

    Returns ``(transcript_metrics, audio_metrics, comparison_metrics,
    skipped_scores)``.

    * ``transcript_metrics`` — LLM-judged metrics that score the transcript
      (today's default behavior). Every transcript metric also receives
      a "## Imported Columns" block built from the row's full
      ``raw_columns`` (see ``_build_all_columns_block``) so the LLM has
      universal access to the CSV row regardless of the metric's
      definition.
    * ``audio_metrics`` — name-based audio-only metrics with a recording
      available.
    * ``comparison_metrics`` — LLM-judged metrics whose ``compare_transcripts``
      flag is set, OR whose description references the production /
      diarised transcripts in well-known phrases (see
      ``_metric_text_references_production``). Both paths require the
      row to have BOTH a production transcript and a diarised
      transcript; otherwise the metric is reported as skipped.
    * ``skipped_scores`` — pre-built ``metric_scores`` entries for the
      cases that can't be evaluated on this row (audio missing or
      either transcript missing for a comparison metric). They still
      surface in the UI with an explanation instead of being silently
      dropped.
    """

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

        # Transcript-compare judge metrics read BOTH transcripts on the
        # row instead of "the" transcript. We treat the metric as a
        # transcript-compare metric when EITHER the explicit
        # ``compare_transcripts`` boolean is set, OR the metric's
        # description references the production / diarised transcripts
        # in well-known phrases (see
        # ``_metric_text_references_production``). Keyword detection
        # only fires for standalone metrics here; parent-grouped
        # metrics get the same treatment later in the worker (we don't
        # have the parent row in scope at categorize time, and the
        # transcript loop already groups by parent_id).
        is_explicit_compare = bool(getattr(m, "compare_transcripts", False))
        is_standalone = not getattr(m, "parent_metric_id", None)
        is_auto_compare = (
            is_standalone
            and has_production_transcript
            and has_diarised_transcript
            and _metric_text_references_production(m)
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
def evaluate_call_import_row_task(
    self,
    eval_row_id: str,
    restricted_metric_ids: Optional[List[str]] = None,
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

        # Pick which transcript column to score against based on the
        # parent evaluation's ``transcript_source`` — 'production' reads
        # the CSV-supplied value, 'diarised' reads the worker-produced
        # value. Legacy / API-omitted runs (NULL ``transcript_source``)
        # now prefer the diarised transcript when one is available, and
        # only fall back to the production transcript when no diarised
        # text exists yet. New evaluations created via the API are
        # always stamped ``transcript_source='diarised'`` by the
        # schema validator; the fallback here protects rows imported
        # / scored under the legacy flow.
        production_transcript = (source_row.transcript or "").strip()
        diarised_transcript = (source_row.diarised_transcript or "").strip()
        raw_source = (evaluation.transcript_source or "").strip().lower()
        if raw_source:
            transcript_source = raw_source
        elif diarised_transcript:
            transcript_source = "diarised"
        else:
            transcript_source = "production"
        if transcript_source == "diarised":
            transcript = diarised_transcript
            missing_label = "diarised"
        else:
            transcript = production_transcript
            missing_label = "production"
        recording_s3_key = (source_row.recording_s3_key or "").strip() or None
        has_audio = recording_s3_key is not None

        metric_ids_raw = evaluation.selected_metric_ids or []
        metric_ids = []
        for item in metric_ids_raw:
            try:
                metric_ids.append(UUID(str(item)))
            except (TypeError, ValueError):
                continue

        # Metric-subset retry: narrow ``metric_ids`` to the requested
        # subset BEFORE the DB query so we don't even hit the
        # categoriser for metrics we're not recomputing. The intersection
        # with ``selected_metric_ids`` defends against a stale payload
        # asking for a metric that's since been removed from the run.
        restricted_metric_uuids: Optional[List[UUID]] = None
        if restricted_metric_ids:
            restricted_metric_uuids = []
            for raw in restricted_metric_ids:
                try:
                    restricted_metric_uuids.append(UUID(str(raw)))
                except (TypeError, ValueError):
                    continue
            metric_ids = [
                mid for mid in metric_ids if mid in restricted_metric_uuids
            ]
            if not metric_ids:
                # Nothing left to do — leave the row alone (preserve
                # its prior status and scores) and surface a typed
                # short-circuit so the rollup can treat it as a no-op.
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

        # Build the "Imported Columns" block ONCE per row and pass it
        # to every LLM call below. This injects all raw CSV columns
        # into the prompt by default so the LLM has full row context
        # for every metric (replaces the legacy per-metric
        # ``input_columns`` flow). ``None`` when the row has no raw
        # columns; the prompt builder skips the section in that case.
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

        # ai_providers is loaded lazily on first LLM call below so we
        # don't re-query for rows that only have audio metrics.
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

        # Transcript-compare judge metrics: one LLM call per metric.
        # v1 keeps these standalone (the schema validator rejects
        # parent_metric_id / selection_mode + compare_transcripts) so
        # we don't need the hierarchical grouping logic the transcript
        # loop uses below.
        # The (production, diarised) pair is passed via the prompt
        # builder's ``comparison_pair`` kwarg which swaps the single
        # "Conversation Transcript" section for a labeled pair.
        if comparison_metrics:
            run_provider = (evaluation.llm_provider or "").strip() or None
            run_model = (evaluation.llm_model or "").strip() or None
            overrides = (
                evaluation.metric_llm_overrides
                if isinstance(evaluation.metric_llm_overrides, dict)
                else {}
            )
            for cmp_metric in comparison_metrics:
                override = overrides.get(str(cmp_metric.id)) or {}
                provider = override.get("provider") or run_provider or None
                model = override.get("model") or run_model or None
                evaluator_obj = None
                if provider and model:
                    evaluator_obj = SimpleNamespace(
                        llm_provider=provider,
                        llm_model=model,
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
