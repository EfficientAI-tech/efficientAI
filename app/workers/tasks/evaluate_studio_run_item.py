"""Celery task: evaluate one Metrics Studio run result."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models.database import (
    AIProvider,
    MetricStudioRun,
    MetricStudioRunResult,
)
from app.services.metric_studio.metric_selection import load_studio_run_metrics
from app.services.metric_studio.source_resolver import resolve_source
from app.workers.config import celery_app
from app.workers.tasks.evaluate_call_import_row_core import (
    bucket_needs_comparison_pair,
    build_llm_config_buckets,
    categorize_metrics,
)
from app.workers.tasks.helpers.audio_evaluation import (
    evaluate_audio_metrics,
    handle_audio_evaluation_error,
)
from app.workers.tasks.helpers.llm_evaluation import (
    evaluate_with_llm,
    flatten_metric_groups,
    handle_llm_evaluation_error,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _rollup_run(db: Session, run: MetricStudioRun) -> None:
    results = (
        db.query(MetricStudioRunResult)
        .filter(MetricStudioRunResult.run_id == run.id)
        .all()
    )
    completed = sum(1 for r in results if r.status == "completed")
    failed = sum(1 for r in results if r.status == "failed")
    pending = sum(1 for r in results if r.status in {"pending", "running"})
    run.completed_items = completed
    run.failed_items = failed
    if pending:
        run.status = "running"
    elif failed and completed:
        run.status = "partial"
        run.finished_at = _now_utc()
    elif failed:
        run.status = "failed"
        run.finished_at = _now_utc()
    else:
        run.status = "completed"
        run.finished_at = _now_utc()
    db.commit()


@celery_app.task(
    bind=True,
    name="evaluate_studio_run_item",
    max_retries=0,
)
def evaluate_studio_run_item_task(self, result_row_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        try:
            row_uuid = UUID(result_row_id)
        except ValueError:
            return {"status": "error", "detail": "invalid result id"}

        result_row = (
            db.query(MetricStudioRunResult)
            .filter(MetricStudioRunResult.id == row_uuid)
            .first()
        )
        if not result_row:
            return {"status": "error", "detail": "result not found"}

        run = (
            db.query(MetricStudioRun)
            .filter(MetricStudioRun.id == result_row.run_id)
            .first()
        )
        if not run:
            return {"status": "error", "detail": "run not found"}

        result_row.status = "running"
        result_row.started_at = result_row.started_at or _now_utc()
        db.commit()

        sample = resolve_source(
            db,
            organization_id=run.organization_id,
            workspace_id=run.workspace_id,
            source_kind=result_row.source_kind,
            source_ref=result_row.source_ref,
            display_label=result_row.display_label,
        )

        transcript_source = (run.transcript_source or "diarised").lower()
        if transcript_source == "production":
            transcript = sample.transcript
        else:
            transcript = sample.diarised_transcript or sample.transcript

        metric_ids = []
        for item in run.selected_metric_ids or []:
            try:
                metric_ids.append(UUID(str(item)))
            except (TypeError, ValueError):
                continue

        metrics = load_studio_run_metrics(db, run.organization_id, metric_ids)
        has_audio = bool(sample.audio_s3_key)
        has_production = bool((sample.transcript or "").strip())
        has_diarised = bool((sample.diarised_transcript or "").strip())

        transcript_metrics, audio_metrics, comparison_metrics, skipped = categorize_metrics(
            metrics,
            has_audio,
            has_production_transcript=has_production,
            has_diarised_transcript=has_diarised,
        )
        llm_metrics = transcript_metrics + comparison_metrics
        metric_scores: dict[str, Any] = dict(skipped)

        if not transcript and not has_audio:
            result_row.status = "failed"
            result_row.error_message = "No transcript or audio available for this source."
            result_row.finished_at = _now_utc()
            db.commit()
            _rollup_run(db, run)
            return {"status": "failed"}

        ai_providers = (
            db.query(AIProvider)
            .filter(
                AIProvider.organization_id == run.organization_id,
                AIProvider.is_active.is_(True),
            )
            .all()
        )

        if audio_metrics and sample.audio_s3_key:
            try:
                audio_scores = evaluate_audio_metrics(
                    audio_s3_key=sample.audio_s3_key,
                    audio_metrics=audio_metrics,
                    result_id=f"studio:{result_row.id}",
                )
                metric_scores.update(audio_scores)
            except Exception as audio_err:
                logger.error(
                    f"[MetricStudio {result_row.id}] audio evaluation failed: {audio_err}",
                    exc_info=True,
                )
                metric_scores.update(
                    handle_audio_evaluation_error(audio_metrics, audio_err)
                )

        if llm_metrics and transcript:
            result_id = f"studio:{result_row.id}"
            production_text = (sample.transcript or "").strip()
            diarised_text = (sample.diarised_transcript or "").strip()
            comparison_ids = {
                str(m.id)
                for m in llm_metrics
                if getattr(m, "compare_transcripts", False)
            }
            buckets = build_llm_config_buckets(
                db,
                llm_metrics,
                overrides={},
                run_provider=None,
                run_model=None,
                run_llm_config=None,
                run_credential_id=None,
            )
            try:
                for _config, groups in buckets.items():
                    comparison_pair = None
                    if bucket_needs_comparison_pair(
                        groups,
                        production_transcript=production_text,
                        diarised_transcript=diarised_text,
                        comparison_metric_ids=comparison_ids,
                    ):
                        comparison_pair = (production_text, diarised_text)
                    bucket_metrics = flatten_metric_groups(groups)
                    scores, _ = evaluate_with_llm(
                        transcription=transcript,
                        llm_metrics=bucket_metrics,
                        ai_providers=ai_providers,
                        organization_id=run.organization_id,
                        result_id=result_id,
                        db=db,
                        comparison_pair=comparison_pair,
                        metric_groups=groups,
                    )
                    metric_scores.update(scores)
            except Exception as llm_err:
                metric_scores.update(handle_llm_evaluation_error(llm_metrics, llm_err))

        result_row.metric_scores = metric_scores
        flag_modified(result_row, "metric_scores")
        metadata = dict(result_row.source_metadata or sample.metadata or {})
        metadata.update(sample.metadata or {})
        if transcript:
            metadata["evaluation_transcript"] = transcript
        metadata["transcript_source_used"] = transcript_source
        result_row.source_metadata = metadata
        flag_modified(result_row, "source_metadata")
        result_row.status = "completed"
        result_row.error_message = None
        result_row.finished_at = _now_utc()
        db.commit()
        _rollup_run(db, run)
        return {"status": "completed", "scores": len(metric_scores)}
    except Exception as exc:
        logger.error(
            f"[MetricStudio] evaluate_studio_run_item failed: {exc}",
            exc_info=True,
        )
        try:
            result_row = (
                db.query(MetricStudioRunResult)
                .filter(MetricStudioRunResult.id == UUID(result_row_id))
                .first()
            )
            if result_row:
                result_row.status = "failed"
                result_row.error_message = str(exc)
                result_row.finished_at = _now_utc()
                db.commit()
                run = (
                    db.query(MetricStudioRun)
                    .filter(MetricStudioRun.id == result_row.run_id)
                    .first()
                )
                if run:
                    _rollup_run(db, run)
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()
