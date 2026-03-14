"""Celery task: process evaluator result (transcribe and evaluate metrics)."""

import time
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.models.database import ModelProvider

from app.workers.config import celery_app
from app.workers.tasks.helpers.constants import (
    REMOVED_EVALUATION_METRIC_NAMES,
    AUDIO_ONLY_METRIC_NAMES,
)
from app.workers.tasks.helpers.score_utils import provider_matches, get_metric_type_value
from app.workers.tasks.helpers.audio_evaluation import (
    evaluate_audio_metrics,
    handle_audio_evaluation_error,
)
from app.workers.tasks.helpers.llm_evaluation import (
    evaluate_with_llm,
    handle_llm_evaluation_error,
)


def _load_related_entities(db, result):
    """Load evaluator, agent, persona, scenario from database."""
    from app.models.database import Evaluator, Agent, Persona, Scenario

    evaluator = None
    if result.evaluator_id:
        evaluator = db.query(Evaluator).filter(Evaluator.id == result.evaluator_id).first()
        if not evaluator:
            logger.warning(
                f"[EvaluatorResult {result.result_id}] Evaluator {result.evaluator_id} not found, "
                "continuing without evaluator"
            )

    agent = None
    if result.agent_id:
        agent = db.query(Agent).filter(Agent.id == result.agent_id).first()

    persona = None
    if result.persona_id:
        persona = db.query(Persona).filter(Persona.id == result.persona_id).first()

    scenario = None
    if result.scenario_id:
        scenario = db.query(Scenario).filter(Scenario.id == result.scenario_id).first()

    return evaluator, agent, persona, scenario


def _transcribe_audio(result, ai_providers, db):
    """Transcribe audio file and return transcript with timing info."""
    from app.services.ai.transcription_service import transcription_service

    stt_provider = ModelProvider.OPENAI
    stt_model = "whisper-1"

    openai_provider = next(
        (p for p in ai_providers if provider_matches(p.provider, ModelProvider.OPENAI)),
        None,
    )
    if not openai_provider:
        logger.warning(
            f"[EvaluatorResult {result.result_id}] No OpenAI provider found, using default whisper-1"
        )

    transcription_start_time = time.time()
    transcription_result = transcription_service.transcribe(
        audio_file_key=result.audio_s3_key,
        stt_provider=stt_provider,
        stt_model=stt_model,
        organization_id=result.organization_id,
        db=db,
        language=None,
        enable_speaker_diarization=True,
    )
    transcription_time = time.time() - transcription_start_time

    return (
        transcription_result.get("transcript", ""),
        transcription_result.get("speaker_segments", []),
        transcription_time,
    )


def _categorize_metrics(enabled_metrics, has_audio):
    """Split metrics into LLM-evaluable and audio-only categories."""
    llm_metrics = []
    audio_metrics = []
    skipped_scores = {}

    for m in enabled_metrics:
        if m.name.lower() in AUDIO_ONLY_METRIC_NAMES:
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


@celery_app.task(name="process_evaluator_result", bind=True, max_retries=3)
def process_evaluator_result_task(self, result_id: str):
    """
    Celery task to process an evaluator result: transcribe audio and evaluate metrics.

    Workflow:
    1. QUEUED -> Job is created and queued
    2. TRANSCRIBING -> Audio is being transcribed
    3. EVALUATING -> Transcription is being evaluated against metrics
    4. COMPLETED -> All processing is complete
    5. FAILED -> An error occurred
    """
    db = SessionLocal()
    task_start_time = time.time()

    try:
        from app.models.database import (
            EvaluatorResult,
            EvaluatorResultStatus,
            Metric,
            AIProvider,
        )

        result_uuid = UUID(result_id)
        result = db.query(EvaluatorResult).filter(EvaluatorResult.id == result_uuid).first()

        if not result:
            logger.error(f"[EvaluatorResult {result_id}] Job not found in database")
            return {"error": "Evaluator result not found"}

        logger.info(f"[EvaluatorResult {result.result_id}] Starting processing task")

        result.celery_task_id = self.request.id
        db.commit()

        has_existing_transcript = bool(result.transcription)

        try:
            if not result.audio_s3_key and not has_existing_transcript:
                raise ValueError("No audio S3 key or existing transcript found")

            evaluator, agent, persona, scenario = _load_related_entities(db, result)
            is_custom_evaluator = evaluator and bool(evaluator.custom_prompt)

            if not is_custom_evaluator and not agent:
                raise ValueError("Agent not found and no custom prompt available")

            ai_providers = db.query(AIProvider).filter(
                AIProvider.organization_id == result.organization_id,
                AIProvider.is_active == True,
            ).all()

            # Step 1: Transcription
            if has_existing_transcript:
                transcription = result.transcription
                speaker_segments = result.speaker_segments or []
                transcription_time = 0.0
            else:
                result.status = EvaluatorResultStatus.TRANSCRIBING.value
                db.commit()

                transcription, speaker_segments, transcription_time = _transcribe_audio(
                    result, ai_providers, db
                )
                result.transcription = transcription
                result.speaker_segments = speaker_segments if speaker_segments else None
                db.commit()

            # Step 2: Load and categorize metrics
            enabled_metrics = db.query(Metric).filter(
                Metric.organization_id == result.organization_id,
                Metric.enabled == True,
            ).all()
            enabled_metrics = [
                m for m in enabled_metrics
                if (m.name or "").strip().lower() not in REMOVED_EVALUATION_METRIC_NAMES
            ]

            has_audio = bool(result.audio_s3_key)
            llm_metrics, audio_metrics, metric_scores = _categorize_metrics(enabled_metrics, has_audio)

            evaluation_time = None

            # Step 3: Audio metrics evaluation
            if audio_metrics and has_audio:
                try:
                    audio_scores = evaluate_audio_metrics(
                        audio_s3_key=result.audio_s3_key,
                        audio_metrics=audio_metrics,
                        result_id=result.result_id,
                    )
                    metric_scores.update(audio_scores)
                except Exception as audio_err:
                    logger.error(
                        f"[EvaluatorResult {result.result_id}] Audio analysis failed: {audio_err}",
                        exc_info=True,
                    )
                    metric_scores.update(handle_audio_evaluation_error(audio_metrics, audio_err))

            # Step 4: LLM metrics evaluation
            if llm_metrics and transcription:
                result.status = EvaluatorResultStatus.EVALUATING.value
                db.commit()

                try:
                    llm_scores, evaluation_time = evaluate_with_llm(
                        transcription=transcription,
                        llm_metrics=llm_metrics,
                        ai_providers=ai_providers,
                        organization_id=result.organization_id,
                        result_id=result.result_id,
                        db=db,
                        evaluator=evaluator,
                        agent=agent,
                        persona=persona,
                        scenario=scenario,
                    )
                    metric_scores.update(llm_scores)
                except Exception as llm_err:
                    error_msg = str(llm_err).replace("{", "{{").replace("}", "}}")
                    logger.error(
                        f"[EvaluatorResult {result.result_id}] ✗ LLM evaluation failed: {error_msg}",
                        exc_info=True,
                    )
                    metric_scores.update(handle_llm_evaluation_error(llm_metrics, llm_err))
            else:
                if not llm_metrics:
                    logger.warning(
                        f"[EvaluatorResult {result.result_id}] No LLM-evaluable metrics found "
                        "(audio-only metrics were skipped), skipping evaluation"
                    )
                if not transcription:
                    logger.warning(
                        f"[EvaluatorResult {result.result_id}] No transcription available, "
                        "skipping evaluation"
                    )

            # Step 5: Complete
            result.metric_scores = metric_scores
            result.status = EvaluatorResultStatus.COMPLETED.value
            db.commit()

            total_time = time.time() - task_start_time
            logger.info(
                f"[EvaluatorResult {result.result_id}] Completed in {total_time:.2f}s, "
                f"{len(metric_scores)} metrics evaluated"
            )

            return {
                "result_id": result_id,
                "status": "completed",
                "transcription": transcription,
                "metrics_evaluated": len(metric_scores),
                "processing_time": total_time,
                "transcription_time": transcription_time,
                "evaluation_time": evaluation_time,
            }

        except Exception as e:
            logger.error(f"[EvaluatorResult {result.result_id}] Processing failed: {e}", exc_info=True)
            result.status = EvaluatorResultStatus.FAILED.value
            result.error_message = str(e)
            db.commit()
            raise

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
