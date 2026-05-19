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


def _metric_input_columns(metric: Metric) -> list[str]:
    """Return the (cleaned) list of column identifiers a metric reads.

    Each entry is either a CSV header (from ``CallImport.extra_columns``)
    or a friendly name the uploader gave a column during import (a key
    of ``CallImport.custom_column_mapping``). The worker resolves both
    shapes against ``raw_columns`` — see ``_resolve_column_value`` —
    so the metric editor can store whichever identifier the user
    actually picked from the column picker.

    Tolerates legacy rows where the column was NULL or contains stray
    non-string entries. Returning an empty list means "this metric scores
    the transcript like before".
    """
    raw = getattr(metric, "input_columns", None) or []
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(h).strip() for h in raw if h is not None and str(h).strip() != ""]


def _resolve_column_value(
    header: str,
    raw_columns: dict[str, Any],
    custom_column_mapping: dict[str, Any] | None,
) -> Any:
    """Look up ``header`` in ``raw_columns`` with a friendly-name fallback.

    ``raw_columns`` is keyed by the *uploader's CSV header* (the verbatim
    column label from the source spreadsheet). The metric editor also
    lets users pick a column by its *friendly name* — the key half of
    ``CallImport.custom_column_mapping`` — because that's what the rest
    of the call-import UI surfaces. When the metric stored a friendly
    name we resolve it here:

      1. Exact key match in ``raw_columns`` (case-sensitive). Handles
         ``extra_columns`` entries and any custom-mapped column whose
         friendly name happens to equal its CSV header.
      2. Case-insensitive key match in ``raw_columns``. Handles minor
         casing drift across imports of the same logical column.
      3. Lookup in ``custom_column_mapping`` (case-insensitive on the
         friendly name) → translate to CSV header → lookup in
         ``raw_columns``. This is what makes a metric storing
         "customer_intent" work across two imports that map that name
         to "Intent_v2" in one batch and "Intent_Final" in the next.

    Returns ``None`` when no resolution path produces a value.
    """
    if header in raw_columns:
        return raw_columns[header]

    header_lower = header.lower()
    for key, value in raw_columns.items():
        if isinstance(key, str) and key.lower() == header_lower:
            return value

    if isinstance(custom_column_mapping, dict):
        for friendly_name, csv_header in custom_column_mapping.items():
            if (
                isinstance(friendly_name, str)
                and friendly_name.lower() == header_lower
                and isinstance(csv_header, str)
            ):
                if csv_header in raw_columns:
                    return raw_columns[csv_header]
                csv_lower = csv_header.lower()
                for key, value in raw_columns.items():
                    if isinstance(key, str) and key.lower() == csv_lower:
                        return value
                return None

    return None


def _build_column_context_block(
    metric: Metric,
    raw_columns: dict[str, Any] | None,
    custom_column_mapping: dict[str, Any] | None = None,
) -> tuple[str | None, list[str]]:
    """Build the "Context Inputs" block for a column-input metric.

    Returns ``(context_text, missing_headers)``. ``context_text`` is
    ``None`` when one or more required headers are missing or empty on
    the source row — the caller treats that as "skip this metric for
    this row" so the UI shows an explanation instead of a hallucinated
    score.

    Headers can be either CSV labels or friendly names — see
    ``_resolve_column_value``. The label rendered in the LLM prompt is
    the metric's stored identifier, which is what the user is mentally
    referring to in the metric description.
    """
    headers = _metric_input_columns(metric)
    if not headers:
        return None, []

    raw_map = raw_columns if isinstance(raw_columns, dict) else {}
    mapping = custom_column_mapping if isinstance(custom_column_mapping, dict) else {}
    lines: list[str] = []
    missing: list[str] = []
    for header in headers:
        value = _resolve_column_value(header, raw_map, mapping)
        if value is None or str(value).strip() == "":
            missing.append(header)
            continue
        # Strip and bound each cell so a multi-MB CSV cell can't bloat
        # the prompt past the model's context window.
        text = str(value).strip()
        if len(text) > 4000:
            text = text[:4000] + "…"
        lines.append(f"- {header}: {text}")

    if missing:
        return None, missing

    return "\n".join(lines), []


def _categorize_metrics(
    metrics: list[Metric],
    has_audio: bool,
    raw_columns: dict[str, Any] | None,
    custom_column_mapping: dict[str, Any] | None = None,
    has_production_transcript: bool = False,
    has_diarised_transcript: bool = False,
) -> tuple[
    list[Metric],
    list[Metric],
    list[tuple[Metric, str]],
    list[Metric],
    dict[str, dict[str, Any]],
]:
    """Split selected metrics into transcript-LLM, audio, column-input,
    and transcript-compare buckets.

    Returns ``(transcript_metrics, audio_metrics, column_metrics,
    comparison_metrics, skipped_scores)``.

    * ``transcript_metrics`` — LLM-judged metrics that score the transcript
      (today's default behavior).
    * ``audio_metrics`` — name-based audio-only metrics with a recording
      available.
    * ``column_metrics`` — pairs of ``(metric, context_block)`` for
      "column-input judge" metrics whose required CSV columns are all
      present on the row. The pre-built context block is what the worker
      passes to ``evaluate_with_llm`` as ``extra_context``.
    * ``comparison_metrics`` — LLM-judged metrics with
      ``compare_transcripts=True`` whose row has BOTH a production
      transcript and a diarised transcript. The worker scores them by
      passing both transcripts to the LLM as a labeled pair.
    * ``skipped_scores`` — pre-built ``metric_scores`` entries for the
      cases that can't be evaluated on this row (audio missing, required
      input columns missing, either transcript missing for a
      comparison metric). They still surface in the UI with an
      explanation instead of being silently dropped.
    """

    transcript_metrics: list[Metric] = []
    audio_metrics: list[Metric] = []
    column_metrics: list[tuple[Metric, str]] = []
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
        # row instead of "the" transcript. They're checked BEFORE the
        # column-input branch because the schema validator guarantees
        # the two flags are mutually exclusive; checking here keeps the
        # routing trivially unambiguous if that invariant ever weakens.
        if bool(getattr(m, "compare_transcripts", False)):
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

        # Column-input judge metrics read named CSV cells from the
        # source row's ``raw_columns`` instead of the transcript. When
        # any required cell is missing on this row we mark the metric
        # as skipped so the user sees a clear reason rather than a
        # transcript-based hallucination.
        if _metric_input_columns(m):
            context_block, col_missing = _build_column_context_block(
                m, raw_columns, custom_column_mapping
            )
            if context_block is None:
                skipped_scores[str(m.id)] = {
                    "value": None,
                    "type": get_metric_type_value(m),
                    "metric_name": m.name,
                    "skipped": "columns_missing",
                    "missing_columns": col_missing,
                }
                continue
            column_metrics.append((m, context_block))
            continue

        transcript_metrics.append(m)

    return (
        transcript_metrics,
        audio_metrics,
        column_metrics,
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

        # Pick which transcript column to score against based on the
        # parent evaluation's ``transcript_source`` — 'production' reads
        # the CSV-supplied value, 'diarised' reads the worker-produced
        # value. Legacy runs (NULL transcript_source) fall back to
        # 'production' so they keep their historical semantics.
        transcript_source = (
            (evaluation.transcript_source or "production").strip().lower()
        )
        production_transcript = (source_row.transcript or "").strip()
        diarised_transcript = (source_row.diarised_transcript or "").strip()
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
            column_metrics,
            comparison_metrics,
            metric_scores,
        ) = _categorize_metrics(
            metrics,
            has_audio,
            raw_columns,
            custom_column_mapping,
            has_production_transcript=bool(production_transcript),
            has_diarised_transcript=bool(diarised_transcript),
        )

        if (
            not transcript_metrics
            and not audio_metrics
            and not column_metrics
            and not comparison_metrics
        ):
            eval_row.status = "failed"
            eval_row.error_message = (
                "Selected metrics could not be evaluated on this row "
                "(missing audio, missing input columns, missing one of "
                "the two transcripts required for a comparison metric, "
                "or no enabled metrics matched)."
            )
            eval_row.metric_scores = _as_json_dict(metric_scores)
            eval_row.finished_at = _now()
            db.commit()
            _rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "no_evaluable_metrics"}

        # Transcript-based LLM metrics still need a transcript. When
        # the run has nothing else to score (no audio, no column-input
        # metrics, no comparison metrics) and the transcript is empty
        # we keep the legacy hard-fail signature so callers who key
        # off ``result["reason"] == "missing_transcript"`` continue to
        # work. When the row also has audio / column / comparison
        # metrics we soft-fail just the transcript bucket so those
        # still produce real scores instead of being held hostage by a
        # missing transcript.
        transcript_unavailable = bool(transcript_metrics) and not transcript
        if (
            transcript_unavailable
            and not audio_metrics
            and not column_metrics
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

        # Column-input judge metrics: evaluate each (metric, context_block)
        # pair on its own. We don't try to fold them into the transcript
        # bucket because their prompt context differs per metric — a
        # shared prompt would either show every column to every metric
        # (leaking inputs) or fail to render cleanly.
        if column_metrics:
            run_provider = (evaluation.llm_provider or "").strip() or None
            run_model = (evaluation.llm_model or "").strip() or None
            overrides = (
                evaluation.metric_llm_overrides
                if isinstance(evaluation.metric_llm_overrides, dict)
                else {}
            )
            for col_metric, context_block in column_metrics:
                override = overrides.get(str(col_metric.id)) or {}
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
                    col_scores, _eval_time = evaluate_with_llm(
                        transcription="",
                        llm_metrics=[col_metric],
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
                        extra_context=context_block,
                    )
                    metric_scores.update(col_scores)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "[CallImportEval {}] Column-input LLM evaluation "
                        "failed for metric={} provider={} model={}",
                        eval_row.id,
                        col_metric.id,
                        provider,
                        model,
                    )
                    metric_scores.update(
                        handle_llm_evaluation_error([col_metric], exc)
                    )
                    evaluation_failed = True
                    primary_error_message = (
                        primary_error_message or str(exc)
                    )

        # Transcript-compare judge metrics: one LLM call per metric,
        # mirroring the column-input loop. v1 keeps these standalone
        # (the schema validator rejects parent_metric_id /
        # selection_mode + compare_transcripts) so we don't need the
        # hierarchical grouping logic the transcript loop uses below.
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
                        extra_context=None,
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
