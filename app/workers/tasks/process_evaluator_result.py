"""Celery task: process evaluator result (transcribe and evaluate metrics)."""

import time
import uuid as _uuid
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


def _make_json_serializable(obj):
    """Recursively convert non-JSON-native values (e.g., NumPy types)."""
    try:
        import numpy as np
    except Exception:
        np = None

    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_json_serializable(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_make_json_serializable(item) for item in obj)

    if np is not None:
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)

    return obj


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


def _generate_call_analysis(transcription, ai_providers, organization_id, result_id, db, agent=None, scenario=None):
    """Generate call analysis (summary, sentiment, success) using LLM."""
    from app.services.ai.llm_service import llm_service

    llm_provider = ModelProvider.OPENAI
    llm_model = "gpt-4o-mini"

    chosen_provider = next(
        (p for p in ai_providers if provider_matches(p.provider, llm_provider)),
        None,
    )
    if not chosen_provider:
        llm_provider = ModelProvider.GOOGLE
        llm_model = "gemini-2.0-flash"
        chosen_provider = next(
            (p for p in ai_providers if provider_matches(p.provider, llm_provider)),
            None,
        )
    if not chosen_provider:
        logger.warning(f"[EvaluatorResult {result_id}] No LLM provider available for call analysis")
        return None

    agent_context = ""
    if agent and agent.description:
        agent_context = f"\n\nAgent Description:\n{agent.description}"
    if scenario:
        scenario_name = getattr(scenario, 'name', '')
        scenario_desc = getattr(scenario, 'description', '')
        if scenario_name or scenario_desc:
            agent_context += f"\n\nScenario: {scenario_name}"
            if scenario_desc:
                agent_context += f"\nScenario Description: {scenario_desc}"

    messages = [
        {
            "role": "system",
            "content": (
                "You are a call analysis expert. Analyze the following conversation transcript "
                "and provide a structured analysis. Respond ONLY with valid JSON, no markdown."
            ),
        },
        {
            "role": "user",
            "content": f"""Analyze this conversation transcript and provide:
1. A concise summary of the call (2-3 sentences)
2. The user/caller's overall sentiment (one of: Positive, Negative, Neutral, Mixed)
3. Whether the call was successful in achieving its objective (true/false)
{agent_context}

Transcript:
{transcription}

Respond in this exact JSON format:
{{"call_summary": "...", "user_sentiment": "...", "call_successful": true/false}}""",
        },
    ]

    try:
        llm_result = llm_service.generate_response(
            messages=messages,
            llm_provider=llm_provider,
            llm_model=llm_model,
            organization_id=organization_id,
            db=db,
            temperature=0.3,
            max_tokens=500,
        )
        import json
        import re
        text = llm_result.get("text", "")
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            analysis = json.loads(json_match.group())
            required_keys = {"call_summary", "user_sentiment", "call_successful"}
            if required_keys.issubset(analysis.keys()):
                logger.info(f"[EvaluatorResult {result_id}] Call analysis generated successfully")
                return analysis
        logger.warning(f"[EvaluatorResult {result_id}] Could not parse call analysis from LLM response")
        return None
    except Exception as e:
        logger.error(f"[EvaluatorResult {result_id}] Call analysis failed: {e}", exc_info=True)
        return None


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


def _normalize_platform(platform: object) -> str:
    """Normalize provider platform enum/string into lowercase string."""
    if not platform:
        return ""
    if hasattr(platform, "value"):
        return str(platform.value).lower()
    return str(platform).lower()


def _extract_audio_url(call_data: dict, platform: str) -> str | None:
    """Extract provider-specific audio URL from call data."""
    recording_urls = call_data.get("recording_urls", {}) if isinstance(call_data, dict) else {}
    provider_payload = call_data.get("provider_payload", {}) if isinstance(call_data, dict) else {}
    artifact = call_data.get("artifact", {}) if isinstance(call_data, dict) else {}
    recording = artifact.get("recording", {}) if isinstance(artifact, dict) else {}
    mono_recording = recording.get("mono", {}) if isinstance(recording, dict) else {}
    if platform == "elevenlabs":
        return recording_urls.get("conversation_audio")
    if platform == "retell":
        return call_data.get("recording_url")
    if platform == "vapi":
        return (
            call_data.get("recordingUrl")
            or call_data.get("stereoRecordingUrl")
            or artifact.get("recordingUrl")
            or artifact.get("stereoRecordingUrl")
            or mono_recording.get("combinedUrl")
            or recording_urls.get("combined_url")
            or recording_urls.get("stereo_url")
            or call_data.get("recordingUrl")
            or provider_payload.get("recordingUrl")
            or provider_payload.get("stereoRecordingUrl")
        )
    if platform == "smallest":
        return (
            call_data.get("recording_url")
            or call_data.get("recordingUrl")
            or recording_urls.get("combined_url")
            or recording_urls.get("conversation_audio")
        )
    return None


def _recover_missing_audio_for_result(result, db, refresh_call_data: bool = True) -> bool:
    """
    Attempt to recover missing audio from provider, upload to S3, and persist key.

    Returns True when a new S3 key is successfully stored.
    """
    import requests as _http

    from app.core.encryption import decrypt_api_key
    from app.models.database import Agent, Integration
    from app.services.storage.s3_service import s3_service
    from app.services.voice_providers import get_voice_provider

    platform = _normalize_platform(result.provider_platform)
    if platform not in {"retell", "vapi", "elevenlabs", "smallest"}:
        return False
    if not result.provider_call_id:
        return False

    agent = db.query(Agent).filter(Agent.id == result.agent_id).first() if result.agent_id else None
    integration = None
    decrypted_key = None
    if agent and agent.voice_ai_integration_id:
        integration = db.query(Integration).filter(
            Integration.id == agent.voice_ai_integration_id,
            Integration.organization_id == result.organization_id,
        ).first()
        if integration:
            try:
                decrypted_key = decrypt_api_key(integration.api_key)
            except Exception as decrypt_err:
                logger.warning(
                    f"[EvaluatorResult {result.result_id}] Unable to decrypt integration key "
                    f"for audio recovery: {decrypt_err}"
                )

    call_data = result.call_data or {}
    if refresh_call_data and decrypted_key:
        try:
            provider_class = get_voice_provider(platform)
            provider_kwargs = {"api_key": decrypted_key}
            if platform == "vapi" and integration and getattr(integration, "public_key", None):
                provider_kwargs["public_key"] = integration.public_key
            provider = provider_class(**provider_kwargs)
            if hasattr(provider, "retrieve_call_metrics"):
                refreshed = provider.retrieve_call_metrics(result.provider_call_id)
                if isinstance(refreshed, dict) and refreshed:
                    call_data = refreshed
                    result.call_data = refreshed
                    db.commit()
        except Exception as refresh_err:
            logger.warning(
                f"[EvaluatorResult {result.result_id}] Audio recovery could not refresh provider metrics: "
                f"{refresh_err}"
            )

    audio_url = _extract_audio_url(call_data, platform)
    if not audio_url:
        logger.warning(
            f"[EvaluatorResult {result.result_id}] Audio recovery failed: no provider recording URL available"
        )
        return False

    headers = {"xi-api-key": decrypted_key} if platform == "elevenlabs" and decrypted_key else None
    try:
        response = _http.get(audio_url, headers=headers, timeout=120)
    except Exception as download_err:
        logger.warning(
            f"[EvaluatorResult {result.result_id}] Audio recovery download failed: {download_err}"
        )
        return False

    if response.status_code != 200 or not response.content:
        logger.warning(
            f"[EvaluatorResult {result.result_id}] Audio recovery download returned "
            f"status={response.status_code}"
        )
        return False

    content_type = response.headers.get("content-type", "audio/mpeg")
    ext = "wav" if "wav" in content_type else "mp3"
    org_id = str(result.organization_id)
    s3_key = (
        f"audio/organizations/{org_id}/evaluations/"
        f"{result.provider_call_id}/{_uuid.uuid4()}.{ext}"
    )

    try:
        s3_service.upload_file_by_key(response.content, s3_key, content_type=content_type)
    except Exception as upload_err:
        logger.warning(
            f"[EvaluatorResult {result.result_id}] Audio recovery upload failed: {upload_err}"
        )
        return False

    result.audio_s3_key = s3_key
    db.commit()
    db.refresh(result)
    logger.info(
        f"[EvaluatorResult {result.result_id}] Recovered missing audio and stored at {s3_key}"
    )
    return True


def _all_audio_scores_download_failed(audio_scores: dict[str, dict[str, object]]) -> bool:
    """Check whether every audio metric failed due to missing/unreadable S3 object."""
    if not audio_scores:
        return False
    return all(
        isinstance(score, dict) and score.get("error") == "audio_download_failed"
        for score in audio_scores.values()
    )


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

        try:
            if not result.audio_s3_key:
                _recover_missing_audio_for_result(result, db, refresh_call_data=True)

            has_existing_transcript = bool(result.transcription)
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
                # Avoid duplicating transcript structure when provider call_data already carries it.
                if not result.call_data:
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

                    if _all_audio_scores_download_failed(audio_scores):
                        logger.warning(
                            f"[EvaluatorResult {result.result_id}] Existing S3 audio unavailable; "
                            "attempting provider audio recovery"
                        )
                        recovered = _recover_missing_audio_for_result(result, db, refresh_call_data=True)
                        if recovered and result.audio_s3_key:
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

            # Step 5: Call Analysis
            if transcription and not (result.call_data and result.call_data.get("call_analysis")):
                try:
                    call_analysis = _generate_call_analysis(
                        transcription=transcription,
                        ai_providers=ai_providers,
                        organization_id=result.organization_id,
                        result_id=result.result_id,
                        db=db,
                        agent=agent,
                        scenario=scenario,
                    )
                    if call_analysis:
                        existing_call_data = dict(result.call_data) if isinstance(result.call_data, dict) else {}
                        existing_call_data["call_analysis"] = call_analysis
                        generated = existing_call_data.get("generated", {})
                        if not isinstance(generated, dict):
                            generated = {}
                        generated["call_analysis"] = call_analysis
                        existing_call_data["generated"] = generated
                        result.call_data = existing_call_data
                except Exception as analysis_err:
                    logger.warning(
                        f"[EvaluatorResult {result.result_id}] Call analysis failed (non-fatal): {analysis_err}"
                    )

            # Step 6: Complete
            result.metric_scores = _make_json_serializable(metric_scores)
            if isinstance(result.call_data, (dict, list)):
                result.call_data = _make_json_serializable(result.call_data)
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
            db.rollback()
            logger.error(f"[EvaluatorResult {result_id}] Processing failed: {e}", exc_info=True)
            try:
                failed_result = db.query(EvaluatorResult).filter(EvaluatorResult.id == result_uuid).first()
                if failed_result:
                    failed_result.status = EvaluatorResultStatus.FAILED.value
                    failed_result.error_message = str(e)
                    db.commit()
            except Exception as persist_err:
                db.rollback()
                logger.error(
                    f"[EvaluatorResult {result_id}] Failed to persist FAILED status: {persist_err}",
                    exc_info=True,
                )
            raise

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
