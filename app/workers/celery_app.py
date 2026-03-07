"""Celery application configuration and task definitions."""

import time
from datetime import datetime
from pathlib import Path
from celery import Celery
from app.config import settings, load_config_from_file
from app.database import SessionLocal
from app.services.evaluation_service import evaluation_service
from uuid import UUID
from loguru import logger

# Load config.yml if it exists (before using settings)
# This ensures the Celery worker has the same configuration as the main app
config_path = Path("config.yml")
if config_path.exists():
    try:
        load_config_from_file(str(config_path))
        logger.info(f"✅ Celery worker loaded configuration from {config_path}")
    except Exception as e:
        logger.warning(f"⚠️  Celery worker: Could not load config.yml: {e}")

# Create Celery app
celery_app = Celery(
    "efficientai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
)


@celery_app.task(name="process_evaluation", bind=True, max_retries=3)
def process_evaluation_task(self, evaluation_id: str):
    """
    Celery task to process an evaluation.

    Args:
        self: Task instance
        evaluation_id: Evaluation ID as string

    Returns:
        Dictionary with evaluation results
    """
    db = SessionLocal()
    try:
        eval_id = UUID(evaluation_id)
        result = evaluation_service.process_evaluation(eval_id, db)
        return result
    except Exception as exc:
        # Retry on failure
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


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
    
    Args:
        self: Task instance
        result_id: EvaluatorResult ID as string
        
    Returns:
        Dictionary with processing results
    """
    db = SessionLocal()
    task_start_time = time.time()
    
    try:
        from app.models.database import (
            EvaluatorResult, EvaluatorResultStatus, Metric, 
            Evaluator, Agent, Persona, Scenario, ModelProvider, AIProvider
        )
        from app.services.transcription_service import transcription_service
        from app.services.llm_service import llm_service
        from app.core.encryption import decrypt_api_key
        import json
        import re
        
        # Helper function to compare provider values (handles string vs enum)
        def provider_matches(db_provider, target_enum):
            """Compare provider field (could be string or enum) with target enum."""
            if db_provider is None:
                return False
            if isinstance(db_provider, str):
                return db_provider.lower() == target_enum.value.lower()
            if hasattr(db_provider, 'value'):
                return db_provider.value.lower() == target_enum.value.lower()
            return db_provider == target_enum
        
        result_uuid = UUID(result_id)
        result = db.query(EvaluatorResult).filter(EvaluatorResult.id == result_uuid).first()
        
        if not result:
            logger.error(f"[EvaluatorResult {result_id}] Job not found in database")
            return {"error": "Evaluator result not found"}
        
        logger.info(f"[EvaluatorResult {result.result_id}] Starting processing task")
        
        # Update Celery task ID
        result.celery_task_id = self.request.id
        db.commit()
        
        # Check if transcript is already available (from provider call_data, or from a previous run)
        has_existing_transcript = bool(result.transcription)
        
        try:
            if not result.audio_s3_key and not has_existing_transcript:
                raise ValueError("No audio S3 key or existing transcript found")
            
            # Evaluator is optional - only load if evaluator_id is present
            evaluator = None
            if result.evaluator_id:
                evaluator = db.query(Evaluator).filter(Evaluator.id == result.evaluator_id).first()
                if not evaluator:
                    logger.warning(f"[EvaluatorResult {result.result_id}] Evaluator {result.evaluator_id} not found, continuing without evaluator")
            
            agent = None
            if result.agent_id:
                agent = db.query(Agent).filter(Agent.id == result.agent_id).first()
            
            persona = None
            if result.persona_id:
                persona = db.query(Persona).filter(Persona.id == result.persona_id).first()
            
            scenario = None
            if result.scenario_id:
                scenario = db.query(Scenario).filter(Scenario.id == result.scenario_id).first()
            
            is_custom_evaluator = evaluator and bool(evaluator.custom_prompt)
            
            if not is_custom_evaluator and not agent:
                raise ValueError("Agent not found and no custom prompt available")
            # Check if organization has configured AI providers (needed for evaluation even if skipping transcription)
            ai_providers = db.query(AIProvider).filter(
                AIProvider.organization_id == result.organization_id,
                AIProvider.is_active == True
            ).all()
            
            if has_existing_transcript:
                transcription = result.transcription
                speaker_segments = result.speaker_segments or []
                transcription_time = 0.0
            else:
                result.status = EvaluatorResultStatus.TRANSCRIBING.value
                db.commit()
                
                stt_provider = ModelProvider.OPENAI
                stt_model = "whisper-1"
                
                openai_provider = next((p for p in ai_providers if provider_matches(p.provider, ModelProvider.OPENAI)), None)
                if not openai_provider:
                    logger.warning(f"[EvaluatorResult {result.result_id}] No OpenAI provider found, using default whisper-1")
                
                transcription_start_time = time.time()
                
                transcription_result = transcription_service.transcribe(
                    audio_file_key=result.audio_s3_key,
                    stt_provider=stt_provider,
                    stt_model=stt_model,
                    organization_id=result.organization_id,
                    db=db,
                    language=None,  # Auto-detect
                    enable_speaker_diarization=True
                )
                
                transcription_time = time.time() - transcription_start_time
                transcription = transcription_result.get("transcript", "")
                speaker_segments = transcription_result.get("speaker_segments", [])
                
                result.transcription = transcription
                result.speaker_segments = speaker_segments if speaker_segments else None
                db.commit()
            
            evaluation_time = None
            
            enabled_metrics = db.query(Metric).filter(
                Metric.organization_id == result.organization_id,
                Metric.enabled == True
            ).all()
            
            # Step 5: Evaluate against enabled metrics using LLM
            metric_scores = {}

            # Audio-dependent metrics require actual audio signal analysis
            # (Parselmouth, ML models). They cannot be evaluated by the LLM
            # from a transcript. When audio IS available they are run through
            # the audio analysis pipeline; otherwise they are skipped.
            AUDIO_ONLY_METRIC_NAMES = {
                "pitch variance", "jitter", "shimmer", "hnr",
                "mos score", "emotion category", "emotion confidence",
                "valence", "arousal", "speaker consistency", "prosody score",
            }

            has_audio = bool(result.audio_s3_key)
            llm_metrics = []
            audio_metrics = []
            for m in enabled_metrics:
                if m.name.lower() in AUDIO_ONLY_METRIC_NAMES:
                    if has_audio:
                        audio_metrics.append(m)
                    else:
                        m_type = m.metric_type.value if hasattr(m.metric_type, 'value') else m.metric_type
                        metric_scores[str(m.id)] = {
                            "value": None,
                            "type": m_type.lower() if isinstance(m_type, str) else m_type,
                            "metric_name": m.name,
                            "skipped": "audio_required",
                        }
                else:
                    llm_metrics.append(m)

            # --- Run audio analysis for audio-dependent metrics ----------------
            if audio_metrics and has_audio:
                try:
                    import tempfile as _tempfile
                    import os as _os
                    from app.services.s3_service import s3_service
                    from app.services.voice_quality_service import calculate_audio_metrics
                    from app.services.qualitative_voice_service import qualitative_voice_service

                    logger.info(f"[EvaluatorResult {result.result_id}] Running audio analysis on {len(audio_metrics)} metrics")
                    audio_bytes = s3_service.download_file_by_key(result.audio_s3_key)
                    if audio_bytes:
                        tmp_fd, tmp_path = _tempfile.mkstemp(suffix=".mp3")
                        _os.close(tmp_fd)
                        try:
                            with open(tmp_path, "wb") as _f:
                                _f.write(audio_bytes)

                            audio_metric_names = [m.name for m in audio_metrics]
                            parselmouth_names = [n for n in audio_metric_names if n.lower() in {"pitch variance", "jitter", "shimmer", "hnr"}]
                            qualitative_names = [n for n in audio_metric_names if n not in parselmouth_names]

                            raw_results: dict = {}
                            if parselmouth_names:
                                raw_results.update(calculate_audio_metrics(tmp_path, parselmouth_names, is_url=False))
                            if qualitative_names:
                                raw_results.update(qualitative_voice_service.calculate_metrics(tmp_path, qualitative_names, is_url=False))

                            for m in audio_metrics:
                                m_type = m.metric_type.value if hasattr(m.metric_type, 'value') else m.metric_type
                                metric_scores[str(m.id)] = {
                                    "value": raw_results.get(m.name),
                                    "type": m_type.lower() if isinstance(m_type, str) else m_type,
                                    "metric_name": m.name,
                                }

                            logger.info(f"[EvaluatorResult {result.result_id}] Audio analysis complete: {list(raw_results.keys())}")
                        finally:
                            if _os.path.exists(tmp_path):
                                _os.unlink(tmp_path)
                    else:
                        logger.warning(f"[EvaluatorResult {result.result_id}] Could not download audio from S3")
                        for m in audio_metrics:
                            m_type = m.metric_type.value if hasattr(m.metric_type, 'value') else m.metric_type
                            metric_scores[str(m.id)] = {
                                "value": None,
                                "type": m_type.lower() if isinstance(m_type, str) else m_type,
                                "metric_name": m.name,
                                "error": "audio_download_failed",
                            }
                except Exception as audio_err:
                    logger.error(f"[EvaluatorResult {result.result_id}] Audio analysis failed: {audio_err}", exc_info=True)
                    for m in audio_metrics:
                        m_type = m.metric_type.value if hasattr(m.metric_type, 'value') else m.metric_type
                        metric_scores[str(m.id)] = {
                            "value": None,
                            "type": m_type.lower() if isinstance(m_type, str) else m_type,
                            "metric_name": m.name,
                            "error": str(audio_err),
                        }
            
            if llm_metrics and transcription:
                result.status = EvaluatorResultStatus.EVALUATING.value
                db.commit()
                # Build metric key mapping for later use
                metric_key_map = {}  # metric_key -> metric object
                for metric in llm_metrics:
                    metric_key = metric.name.lower().replace(" ", "_")
                    metric_key_map[metric_key] = metric
                    metric_key_map[metric.name.lower()] = metric
                
                if is_custom_evaluator:
                    evaluation_prompt = f"""You are evaluating a conversation transcript against the agent's system prompt. You MUST evaluate ONLY the specific metrics listed below and use the EXACT metric keys provided.

## Agent System Prompt
The following is the system prompt / instructions that the agent was configured with. Use this to understand the agent's goals, rules, and expected behavior when evaluating the conversation.

{evaluator.custom_prompt}

## Conversation Transcript
{transcription}

## Metrics to Evaluate (use EXACT keys below)
"""
                else:
                    call_type_val = (agent.call_type.value if hasattr(agent.call_type, 'value') else agent.call_type) if agent and agent.call_type else 'conversations'
                    language_val = (persona.language.value if hasattr(persona.language, 'value') else persona.language) if persona and persona.language else 'N/A'
                    agent_objective = agent.description if agent and agent.description else f"The agent's objective is to handle {call_type_val}."
                    scenario_context = scenario.description if scenario and scenario.description else ""
                    scenario_goals = scenario.required_info if scenario and scenario.required_info else {}
                    
                    evaluation_prompt = f"""You are evaluating a conversation transcript. You MUST evaluate ONLY the specific metrics listed below and use the EXACT metric keys provided.

## Agent Information
- Name: {agent.name if agent else 'Unknown'}
- Objective/Purpose: {agent_objective}
- Call Type: {call_type_val if agent and agent.call_type else 'N/A'}
- Language: {language_val}

## Scenario Information
- Name: {scenario.name if scenario else 'Unknown'}
- Description: {scenario_context}
- Required Information: {json.dumps(scenario_goals) if scenario_goals else 'N/A'}

## Conversation Transcript
{transcription}

## Metrics to Evaluate (use EXACT keys below)
"""
                
                # Add metric descriptions to prompt with exact keys
                for metric in llm_metrics:
                    metric_key = metric.name.lower().replace(" ", "_")
                    metric_desc = metric.description or f"Evaluate {metric.name}"
                    m_type = metric.metric_type.value if hasattr(metric.metric_type, 'value') else metric.metric_type
                    if m_type == "rating":
                        evaluation_prompt += f'\n- "{metric_key}" (rating 0.0-1.0): {metric_desc}'
                    elif m_type == "boolean":
                        evaluation_prompt += f'\n- "{metric_key}" (true/false): {metric_desc}'
                    elif m_type == "number":
                        evaluation_prompt += f'\n- "{metric_key}" (numeric value): {metric_desc}'
                
                evaluation_prompt += f"""

## REQUIRED Response Format
You MUST respond with ONLY a JSON object using the EXACT metric keys listed above. No other keys allowed.

Example format:
{{
"""
                for metric in llm_metrics:
                    metric_key = metric.name.lower().replace(" ", "_")
                    m_type = metric.metric_type.value if hasattr(metric.metric_type, 'value') else metric.metric_type
                    if m_type == "rating":
                        evaluation_prompt += f'  "{metric_key}": 0.75,\n'
                    elif m_type == "boolean":
                        evaluation_prompt += f'  "{metric_key}": true,\n'
                    elif m_type == "number":
                        evaluation_prompt += f'  "{metric_key}": 5,\n'
                
                evaluation_prompt += """}

CRITICAL RULES:
1. Use the EXACT metric keys shown above - copy them character-for-character
2. Each value must be a SINGLE NUMBER (not an object with score/comments)
3. Do NOT wrap in "metrics" or any other object
4. Do NOT add comments or explanations
5. Return ONLY the JSON object, nothing else"""
                
                # Call LLM service for evaluation
                try:
                    # Determine LLM provider and model from evaluator config, falling back to defaults
                    evaluator_llm_provider = getattr(evaluator, 'llm_provider', None) if evaluator else None
                    evaluator_llm_model = getattr(evaluator, 'llm_model', None) if evaluator else None
                    
                    if evaluator_llm_provider and evaluator_llm_model:
                        if isinstance(evaluator_llm_provider, str):
                            llm_provider = ModelProvider(evaluator_llm_provider.lower())
                        else:
                            llm_provider = evaluator_llm_provider
                        llm_model = evaluator_llm_model
                    else:
                        llm_provider = ModelProvider.OPENAI
                        llm_model = "gpt-4o"
                    
                    chosen_provider = next((p for p in ai_providers if provider_matches(p.provider, llm_provider)), None)
                    if not chosen_provider:
                        logger.warning(f"[EvaluatorResult {result.result_id}] Provider {llm_provider.value} not configured, evaluation may fail")
                    
                    # Build the list of exact metric keys for system message
                    exact_keys = [metric.name.lower().replace(" ", "_") for metric in llm_metrics]
                    
                    messages = [
                        {"role": "system", "content": f"""You are an expert conversation evaluator. You MUST follow these rules STRICTLY:

1. Return ONLY valid JSON - no markdown, no explanations, no comments
2. Use ONLY these exact metric keys (copy-paste them exactly): {json.dumps(exact_keys)}
3. Each value must be a single number (0.0-1.0 for ratings, 0 or 1 for boolean) - NO nested objects, NO comments
4. Do NOT rename, abbreviate, or modify the metric keys in any way

Example of CORRECT format:
{{"follow_instructions": 0.8, "clarity_and_empathy": 0.7}}

Example of WRONG format (DO NOT do this):
{{"metrics": {{"Clarity": {{"score": 7}}}}}}"""},
                        {"role": "user", "content": evaluation_prompt}
                    ]
                    
                    evaluation_start_time = time.time()
                    
                    llm_result = llm_service.generate_response(
                        messages=messages,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        organization_id=result.organization_id,
                        db=db,
                        temperature=0.3,  # Lower temperature for more consistent evaluations
                        max_tokens=2000
                    )
                    
                    evaluation_time = time.time() - evaluation_start_time
                    
                    response_text = llm_result["text"].strip()
                    
                    # Try to extract JSON from response (handle cases where LLM adds markdown formatting)
                    if response_text.startswith("```json"):
                        response_text = response_text.replace("```json", "").replace("```", "").strip()
                    elif response_text.startswith("```"):
                        response_text = response_text.replace("```", "").strip()
                    
                    try:
                        evaluation_data = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        logger.warning(f"[EvaluatorResult {result.result_id}] JSON parsing failed, attempting regex extraction")
                        json_match = re.search(r'\{[\s\S]*\}', response_text)
                        if json_match:
                            try:
                                evaluation_data = json.loads(json_match.group())
                            except json.JSONDecodeError:
                                raise ValueError("Could not parse extracted JSON")
                        else:
                            raise ValueError("Could not parse LLM response as JSON")
                    
                    if "metrics" in evaluation_data and isinstance(evaluation_data["metrics"], dict):
                        evaluation_data = evaluation_data["metrics"]
                    
                    # Helper function to extract score from various formats
                    def extract_score(value):
                        """Extract numeric/boolean score from various response formats."""
                        if value is None:
                            return None
                        # Direct value
                        if isinstance(value, (int, float, bool)):
                            return value
                        # Nested object with 'score' field
                        if isinstance(value, dict):
                            if 'score' in value:
                                return value['score']
                            if 'value' in value:
                                return value['value']
                            if 'rating' in value:
                                return value['rating']
                        # String that might be a number
                        if isinstance(value, str):
                            try:
                                return float(value)
                            except ValueError:
                                if value.lower() in ('true', 'yes'):
                                    return True
                                if value.lower() in ('false', 'no'):
                                    return False
                        return None
                    
                    # Helper function to find matching key in response (case-insensitive, fuzzy)
                    def find_matching_key(target_key, response_keys):
                        """Find a matching key in the response, with fuzzy matching."""
                        target_lower = target_key.lower().replace(" ", "_").replace("-", "_")
                        target_words = set(target_lower.replace("_", " ").split())
                        
                        # Exact match (case-insensitive)
                        for key in response_keys:
                            if key.lower().replace(" ", "_").replace("-", "_") == target_lower:
                                return key
                        
                        # Partial match (key contains target or target contains key)
                        for key in response_keys:
                            key_lower = key.lower().replace(" ", "_").replace("-", "_")
                            if target_lower in key_lower or key_lower in target_lower:
                                return key
                        
                        # Word overlap match
                        best_match = None
                        best_overlap = 0
                        for key in response_keys:
                            key_words = set(key.lower().replace("_", " ").replace("-", " ").split())
                            overlap = len(target_words & key_words)
                            if overlap > best_overlap:
                                best_overlap = overlap
                                best_match = key
                        
                        if best_overlap >= 1:  # At least one word matches
                            return best_match
                        
                        return None
                    
                    response_keys = list(evaluation_data.keys())
                    
                    for metric in llm_metrics:
                        metric_key = metric.name.lower().replace(" ", "_")
                        m_type = metric.metric_type.value if hasattr(metric.metric_type, 'value') else metric.metric_type
                        
                        # Try exact key first
                        raw_score = evaluation_data.get(metric_key)
                        
                        # If not found, try fuzzy matching
                        if raw_score is None:
                            matched_key = find_matching_key(metric.name, response_keys)
                            if matched_key:
                                raw_score = evaluation_data.get(matched_key)
                        
                        # Extract score from various formats
                        score = extract_score(raw_score)
                        
                        # Validate and convert score based on metric type
                        if m_type == "rating":
                            if score is not None:
                                try:
                                    score = float(score)
                                    # If score is 0-10 range, normalize to 0-1
                                    if score > 1.0:
                                        score = score / 10.0
                                    # Clamp to 0.0-1.0 range
                                    score = max(0.0, min(1.0, score))
                                except (ValueError, TypeError):
                                    score = None
                        elif m_type == "boolean":
                            if score is not None:
                                if isinstance(score, bool):
                                    pass  # Already boolean
                                elif isinstance(score, (int, float)):
                                    score = score > 0.5 if score <= 1 else score > 5  # Handle 0-1 or 0-10 ranges
                                else:
                                    score = bool(score)
                        elif m_type == "number":
                            if score is not None:
                                try:
                                    score = float(score)
                                except (ValueError, TypeError):
                                    score = None
                        
                        metric_scores[str(metric.id)] = {
                            "value": score,
                            "type": m_type.lower() if isinstance(m_type, str) else m_type,
                            "metric_name": metric.name
                        }
                        
                except Exception as e:
                    # Use str() to avoid format issues with curly braces in error messages
                    error_msg = str(e).replace("{", "{{").replace("}", "}}")
                    logger.error(f"[EvaluatorResult {result.result_id}] ✗ LLM evaluation failed: {error_msg}", exc_info=True)
                    # If LLM evaluation fails, mark metrics as None but don't fail the whole task
                    for metric in llm_metrics:
                        m_type = metric.metric_type.value if hasattr(metric.metric_type, 'value') else metric.metric_type
                        metric_scores[str(metric.id)] = {
                            "value": None,
                            "type": m_type.lower() if isinstance(m_type, str) else m_type,
                            "metric_name": metric.name,
                            "error": str(e)
                        }
            else:
                if not llm_metrics:
                    logger.warning(f"[EvaluatorResult {result.result_id}] No LLM-evaluable metrics found (audio-only metrics were skipped), skipping evaluation")
                if not transcription:
                    logger.warning(f"[EvaluatorResult {result.result_id}] No transcription available, skipping evaluation")
            
            # Update status to COMPLETED
            result.metric_scores = metric_scores
            result.status = EvaluatorResultStatus.COMPLETED.value
            db.commit()
            
            total_time = time.time() - task_start_time
            logger.info(f"[EvaluatorResult {result.result_id}] Completed in {total_time:.2f}s, {len(metric_scores)} metrics evaluated")
            
            return {
                "result_id": result_id,
                "status": "completed",
                "transcription": transcription,
                "metrics_evaluated": len(metric_scores),
                "processing_time": total_time,
                "transcription_time": transcription_time if 'transcription_time' in locals() else None,
                "evaluation_time": evaluation_time if 'evaluation_time' in locals() else None
            }
            
        except Exception as e:
            # Mark as failed
            logger.error(f"[EvaluatorResult {result.result_id}] Processing failed: {e}", exc_info=True)
            result.status = EvaluatorResultStatus.FAILED.value
            result.error_message = str(e)
            db.commit()
            raise
            
    except Exception as exc:
        # Retry on failure
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="run_evaluator", bind=True, max_retries=3)
def run_evaluator_task(self, evaluator_id: str, evaluator_result_id: str):
    """
    Celery task to run an evaluator: bridge test agent to Voice AI agent and record conversation.
    
    Args:
        self: Task instance
        evaluator_id: Evaluator ID as string
        evaluator_result_id: Pre-created EvaluatorResult ID as string
        
    Returns:
        Dictionary with execution results
    """
    db = SessionLocal()
    task_start_time = time.time()
    
    try:
        from app.models.database import (
            Evaluator, EvaluatorResult, EvaluatorResultStatus,
            Agent, Persona, Scenario
        )
        from app.services.test_agent_bridge_service import test_agent_bridge_service
        import asyncio
        
        evaluator_uuid = UUID(evaluator_id)
        result_uuid = UUID(evaluator_result_id)
        
        evaluator = db.query(Evaluator).filter(Evaluator.id == evaluator_uuid).first()
        if not evaluator:
            logger.error(f"[RunEvaluator {evaluator_id}] Evaluator not found")
            return {"error": "Evaluator not found"}
        
        result = db.query(EvaluatorResult).filter(EvaluatorResult.id == result_uuid).first()
        if not result:
            logger.error(f"[RunEvaluator {evaluator_id}] EvaluatorResult not found")
            return {"error": "EvaluatorResult not found"}
        
        agent = db.query(Agent).filter(Agent.id == evaluator.agent_id).first()
        if not agent:
            logger.error(f"[RunEvaluator {evaluator_id}] Agent not found")
            result.status = EvaluatorResultStatus.FAILED.value
            result.error_message = "Agent not found"
            db.commit()
            return {"error": "Agent not found"}
        
        logger.info(f"[RunEvaluator {evaluator.evaluator_id}] Starting task (Result: {result.result_id})")
        
        result.celery_task_id = self.request.id
        if result.status != EvaluatorResultStatus.QUEUED.value:
            logger.warning(f"[RunEvaluator {evaluator.evaluator_id}] Status was {result.status}, expected QUEUED")
        db.commit()
        
        has_voice_bundle = agent.voice_bundle_id is not None
        has_voice_ai_integration = agent.voice_ai_integration_id is not None and agent.voice_ai_agent_id is not None
        
        if has_voice_bundle and has_voice_ai_integration:
            
            try:
                result.status = EvaluatorResultStatus.CALL_INITIATING.value
                result.call_event = "task_started"
                db.commit()
                
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                bridge_result = loop.run_until_complete(
                    test_agent_bridge_service.bridge_test_agent_to_voice_agent(
                        evaluator_id=evaluator_uuid,
                        evaluator_result_id=result_uuid,
                        organization_id=evaluator.organization_id,
                        db=db,
                    )
                )
                
                # Don't reset status - the bridge service should have updated it
                # Refresh the result to get the latest status from the bridge service
                db.refresh(result)
                
                # Only update error_message if it was set to clear any temporary call info
                if result.error_message and result.error_message.startswith("call_id:"):
                    # Keep the call info for now, it will be cleared when call ends
                    pass
                
                db.commit()
                
                return {
                    "evaluator_id": evaluator_id,
                    "result_id": evaluator_result_id,
                    "status": "initiated",
                    "bridge_result": bridge_result,
                }
                
            except Exception as bridge_error:
                logger.error(f"[RunEvaluator {evaluator.evaluator_id}] Bridge service error: {bridge_error}", exc_info=True)
                result.status = EvaluatorResultStatus.FAILED.value
                result.error_message = str(bridge_error)
                result.call_event = "bridge_error"
                db.commit()
                raise
        
        elif has_voice_bundle:
            result.status = EvaluatorResultStatus.FAILED.value
            result.error_message = "Standard voice agent flow not yet implemented for evaluator runs"
            db.commit()
            return {"error": "Standard flow not implemented"}
        
        else:
            logger.error(f"[RunEvaluator {evaluator.evaluator_id}] Agent missing required configuration")
            result.status = EvaluatorResultStatus.FAILED.value
            result.error_message = f"Agent missing required configuration: voice_bundle={has_voice_bundle}, voice_ai_integration={has_voice_ai_integration}"
            result.call_event = "configuration_error"
            db.commit()
            return {"error": "Agent does not have required configuration for bridging"}
            
    except Exception as exc:
        logger.error(f"[RunEvaluator {evaluator_id}] Task failed: {exc}", exc_info=True)
        # Update result status
        try:
            result = db.query(EvaluatorResult).filter(EvaluatorResult.id == UUID(evaluator_result_id)).first()
            if result:
                result.status = EvaluatorResultStatus.FAILED.value
                result.error_message = str(exc)
                db.commit()
        except:
            pass
        # Retry on failure
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


# ======================================================================
# TTS Comparison Tasks (Voice Playground)
# ======================================================================


@celery_app.task(name="generate_tts_comparison", bind=True, max_retries=1)
def generate_tts_comparison_task(self, comparison_id: str):
    """
    Generate TTS audio for every sample in a comparison, upload to S3,
    then dispatch evaluation.
    """
    from app.models.database import (
        TTSComparison, TTSSample,
        TTSComparisonStatus, TTSSampleStatus, ModelProvider,
    )
    from app.services.tts_service import tts_service, get_audio_file_extension

    db = SessionLocal()
    try:
        comp = db.query(TTSComparison).filter(TTSComparison.id == UUID(comparison_id)).first()
        if not comp:
            logger.error(f"[TTS Generate] Comparison {comparison_id} not found")
            return {"error": "not found"}

        comp.status = TTSComparisonStatus.GENERATING.value
        db.commit()

        samples = (
            db.query(TTSSample)
            .filter(TTSSample.comparison_id == comp.id)
            .order_by(TTSSample.sample_index)
            .all()
        )

        voice_configs_a = {v["id"]: v for v in (comp.voices_a or []) if isinstance(v, dict)}
        voice_configs_b = {v["id"]: v for v in (comp.voices_b or []) if isinstance(v, dict)}

        def _resolve_voice_meta(sample_obj):
            """Match sample to correct side's voice config (A or B)."""
            if sample_obj.side == "A":
                return voice_configs_a.get(sample_obj.voice_id) or {}
            if sample_obj.side == "B":
                return voice_configs_b.get(sample_obj.voice_id) or {}
            # Fallback for legacy samples without a side column
            is_side_a = (
                sample_obj.provider == comp.provider_a and sample_obj.model == comp.model_a
            )
            is_side_b = (
                sample_obj.provider == comp.provider_b and sample_obj.model == comp.model_b
            )
            if is_side_a and not is_side_b:
                return voice_configs_a.get(sample_obj.voice_id) or {}
            if is_side_b and not is_side_a:
                return voice_configs_b.get(sample_obj.voice_id) or {}
            return voice_configs_a.get(sample_obj.voice_id) or voice_configs_b.get(sample_obj.voice_id) or {}

        failed_count = 0
        for sample in samples:
            try:
                sample.status = TTSSampleStatus.GENERATING.value
                db.commit()

                voice_meta = _resolve_voice_meta(sample)
                tts_config = {}
                sample_rate_hz = voice_meta.get("sample_rate_hz")
                if sample_rate_hz:
                    tts_config["sample_rate_hz"] = int(sample_rate_hz)

                provider_enum = ModelProvider(sample.provider)
                logger.info(
                    f"[TTS Generate] Sample {sample.id} – "
                    f"provider={sample.provider} voice={sample.voice_id} "
                    f"sample_rate_hz={sample_rate_hz} config={tts_config}"
                )
                audio_bytes, latency_ms, ttfb_ms = tts_service.synthesize_timed(
                    text=sample.text,
                    tts_provider=provider_enum,
                    tts_model=sample.model,
                    organization_id=comp.organization_id,
                    db=db,
                    voice=sample.voice_id,
                    config=tts_config or None,
                )

                from app.services.s3_service import s3_service

                audio_ext = get_audio_file_extension(sample.provider, int(sample_rate_hz) if sample_rate_hz else None)
                s3_key = s3_service.upload_file_by_key(
                    file_content=audio_bytes,
                    key=f"{s3_service.prefix}organizations/{comp.organization_id}/voicePlayground/{comp.id}/{sample.id}.{audio_ext}",
                )

                if audio_ext == "wav" and len(audio_bytes) > 44:
                    import struct as _struct
                    sr = _struct.unpack_from('<I', audio_bytes, 24)[0]
                    duration_est = (len(audio_bytes) - 44) / (2 * sr) if sr > 0 else None
                else:
                    duration_est = len(audio_bytes) / (128000 / 8) if audio_bytes else None

                sample.audio_s3_key = s3_key
                sample.latency_ms = round(latency_ms, 1)
                sample.ttfb_ms = round(ttfb_ms, 1)
                sample.duration_seconds = round(duration_est, 2) if duration_est else None
                sample.status = TTSSampleStatus.COMPLETED.value
                db.commit()

                logger.info(
                    f"[TTS Generate] Sample {sample.id} done – "
                    f"{sample.provider}/{sample.voice_name} ttfb={ttfb_ms:.0f}ms total={latency_ms:.0f}ms"
                )

            except Exception as e:
                logger.error(f"[TTS Generate] Sample {sample.id} failed: {e}")
                sample.status = TTSSampleStatus.FAILED.value
                sample.error_message = str(e)[:500]
                db.commit()
                failed_count += 1

        total = len(samples)
        if failed_count == total:
            comp.status = TTSComparisonStatus.FAILED.value
            comp.error_message = "All samples failed to generate"
            db.commit()
            return {"error": "all failed"}

        # Dispatch evaluation
        comp.status = TTSComparisonStatus.EVALUATING.value
        db.commit()
        evaluate_tts_comparison_task.delay(comparison_id)

        return {"generated": total - failed_count, "failed": failed_count}

    except Exception as exc:
        logger.error(f"[TTS Generate] Task failed: {exc}", exc_info=True)
        try:
            comp = db.query(TTSComparison).filter(TTSComparison.id == UUID(comparison_id)).first()
            if comp:
                comp.status = TTSComparisonStatus.FAILED.value
                comp.error_message = str(exc)[:500]
                db.commit()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()


def _compute_wer_cer(ground_truth: str, predicted: str):
    """Compute raw and normalized WER/CER between reference and ASR text.

    Normalized scores reduce false penalties on numeric/currency phrasing
    differences (for example "$1,234.56" vs "one thousand two hundred...").
    """
    import re
    import string
    try:
        from jiwer import wer, cer
    except ImportError:
        logger.warning("[TTS Eval] jiwer not installed – skipping WER/CER")
        return {
            "raw_wer": None,
            "raw_cer": None,
            "normalized_wer": None,
            "normalized_cer": None,
        }

    number_words = {
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
        "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
        "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
        "billion", "trillion", "point", "and",
    }
    currency_words = {
        "dollar", "dollars", "usd", "cent", "cents", "rupee", "rupees", "inr",
        "euro", "euros", "eur", "pound", "pounds", "gbp",
    }

    def _is_numeric_token(token: str) -> bool:
        return bool(re.fullmatch(r"\d+(?:\.\d+)?", token))

    def _normalize_base(text: str) -> str:
        punct_table = str.maketrans("", "", string.punctuation)
        return text.lower().translate(punct_table).strip()

    def _normalize_entities(text: str) -> str:
        tokens = _normalize_base(text).split()
        normalized_tokens = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            is_entity_token = (
                _is_numeric_token(token)
                or token in number_words
                or token in currency_words
            )
            if not is_entity_token:
                normalized_tokens.append(token)
                i += 1
                continue

            j = i
            has_currency = token in currency_words
            while j < len(tokens):
                t = tokens[j]
                if _is_numeric_token(t) or t in number_words or t in currency_words:
                    if t in currency_words:
                        has_currency = True
                    j += 1
                    continue
                break

            normalized_tokens.append("<amount>" if has_currency else "<num>")
            i = j

        return " ".join(normalized_tokens)
    ref = _normalize_base(ground_truth)
    hyp = _normalize_base(predicted)

    if not ref:
        return {
            "raw_wer": None,
            "raw_cer": None,
            "normalized_wer": None,
            "normalized_cer": None,
        }

    try:
        raw_wer = round(wer(ref, hyp), 4)
        raw_cer = round(cer(ref, hyp), 4)

        norm_ref = _normalize_entities(ground_truth)
        norm_hyp = _normalize_entities(predicted)
        normalized_wer = round(wer(norm_ref, norm_hyp), 4) if norm_ref else None
        normalized_cer = round(cer(norm_ref, norm_hyp), 4) if norm_ref else None

        return {
            "raw_wer": raw_wer,
            "raw_cer": raw_cer,
            "normalized_wer": normalized_wer,
            "normalized_cer": normalized_cer,
        }
    except Exception as e:
        logger.warning(f"[TTS Eval] WER/CER calculation error: {e}")
        return {
            "raw_wer": None,
            "raw_cer": None,
            "normalized_wer": None,
            "normalized_cer": None,
        }


# Singleton for the NeMo ASR model (loaded once per worker process)
_nemo_asr_model = None


def _get_nemo_asr_model():
    """Lazy-load NVIDIA NeMo Conformer CTC model for hallucination detection.

    Requires: pip install efficientai[nemo-asr]
    Returns the model instance, or None if NeMo is not installed.
    """
    global _nemo_asr_model

    if _nemo_asr_model is not None:
        return _nemo_asr_model

    try:
        import nemo.collections.asr as nemo_asr
        logger.info("[TTS Eval] Loading NeMo ASR model (stt_en_conformer_ctc_large)...")
        _nemo_asr_model = nemo_asr.models.ASRModel.from_pretrained("stt_en_conformer_ctc_large")
        logger.info("[TTS Eval] NeMo ASR model loaded successfully")
        return _nemo_asr_model
    except ImportError as e:
        logger.warning(
            f"[TTS Eval] NeMo import failed: {e} – "
            "WER/CER hallucination metrics will be skipped. "
            "To enable, run:\n"
            "  pip install 'nemo_toolkit[asr]'\n"
            "  python -c \"import nemo.collections.asr as nemo_asr; "
            "nemo_asr.models.ASRModel.from_pretrained('stt_en_conformer_ctc_large')\""
        )
    except Exception as e:
        logger.error(
            f"[TTS Eval] NeMo ASR model failed to load: {e} – "
            "The model may not be cached yet. To download it manually, run:\n"
            "  python -c \"import nemo.collections.asr as nemo_asr; "
            "nemo_asr.models.ASRModel.from_pretrained('stt_en_conformer_ctc_large')\"",
            exc_info=True,
        )

    return None


def _transcribe_audio_for_eval(audio_path: str) -> str | None:
    """Transcribe an audio file using NVIDIA NeMo Conformer CTC.

    Runs entirely on the worker – no API key needed.
    """
    model = _get_nemo_asr_model()
    if model is None:
        return None

    try:
        transcriptions = model.transcribe([audio_path])
        if transcriptions and len(transcriptions) > 0:
            text = transcriptions[0]
            # NeMo may return Hypothesis objects in some versions
            if hasattr(text, "text"):
                text = text.text
            return str(text).strip() or None
        return None
    except Exception as e:
        logger.warning(f"[TTS Eval] ASR transcription failed: {e}")
        return None


@celery_app.task(name="evaluate_tts_comparison", bind=True, max_retries=1)
def evaluate_tts_comparison_task(self, comparison_id: str):
    """
    Download each completed sample from S3 and run qualitative voice
    metrics (MOS, Valence, Arousal, Prosody) plus ASR-based WER/CER
    for hallucination detection.
    """
    import tempfile
    import os
    from app.models.database import (
        TTSComparison, TTSSample, TTSComparisonStatus, TTSSampleStatus,
    )
    from app.services.s3_service import s3_service

    db = SessionLocal()
    try:
        comp = db.query(TTSComparison).filter(TTSComparison.id == UUID(comparison_id)).first()
        if not comp:
            return {"error": "not found"}

        samples = (
            db.query(TTSSample)
            .filter(
                TTSSample.comparison_id == comp.id,
                TTSSample.status == TTSSampleStatus.COMPLETED.value,
                TTSSample.audio_s3_key.isnot(None),
            )
            .all()
        )

        if not samples:
            comp.status = TTSComparisonStatus.COMPLETED.value
            db.commit()
            return {"evaluated": 0}

        # Lazy-load qualitative service inside the worker
        from app.services.qualitative_voice_service import qualitative_voice_service

        # Pre-warm the NeMo ASR model once for the batch (lazy singleton)
        nemo_model = _get_nemo_asr_model()

        evaluated = 0
        for sample in samples:
            tmp_path = None
            try:
                # Download from S3 to temp file
                audio_bytes = s3_service.download_file_by_key(sample.audio_s3_key)
                if not audio_bytes:
                    continue

                tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
                os.close(tmp_fd)
                with open(tmp_path, "wb") as f:
                    f.write(audio_bytes)

                metrics = qualitative_voice_service.calculate_all_metrics(tmp_path)

                # ASR-based hallucination detection (WER / CER)
                if nemo_model is not None and sample.text:
                    asr_transcript = _transcribe_audio_for_eval(tmp_path)
                    if asr_transcript:
                        score_bundle = _compute_wer_cer(sample.text, asr_transcript)
                        metrics["WER Raw"] = score_bundle.get("raw_wer")
                        metrics["CER Raw"] = score_bundle.get("raw_cer")
                        metrics["WER Normalized"] = score_bundle.get("normalized_wer")
                        metrics["CER Normalized"] = score_bundle.get("normalized_cer")
                        metrics["WER"] = (
                            score_bundle.get("normalized_wer")
                            if score_bundle.get("normalized_wer") is not None
                            else score_bundle.get("raw_wer")
                        )
                        metrics["CER"] = (
                            score_bundle.get("normalized_cer")
                            if score_bundle.get("normalized_cer") is not None
                            else score_bundle.get("raw_cer")
                        )
                        metrics["ASR Transcript"] = asr_transcript
                    else:
                        metrics["WER"] = None
                        metrics["CER"] = None
                        metrics["WER Raw"] = None
                        metrics["CER Raw"] = None
                        metrics["WER Normalized"] = None
                        metrics["CER Normalized"] = None
                        metrics["ASR Transcript"] = None

                sample.evaluation_metrics = metrics
                db.commit()
                evaluated += 1

                logger.info(f"[TTS Eval] Sample {sample.id} metrics: {metrics}")

            except Exception as e:
                logger.warning(f"[TTS Eval] Sample {sample.id} eval failed: {e}")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

        # Build summary
        from app.api.v1.routes.voice_playground import _recompute_summary
        _recompute_summary(comp, db)

        comp.status = TTSComparisonStatus.COMPLETED.value
        db.commit()

        logger.info(f"[TTS Eval] Comparison {comparison_id} complete – {evaluated}/{len(samples)} evaluated")
        return {"evaluated": evaluated}

    except Exception as exc:
        logger.error(f"[TTS Eval] Task failed: {exc}", exc_info=True)
        try:
            comp = db.query(TTSComparison).filter(TTSComparison.id == UUID(comparison_id)).first()
            if comp:
                comp.status = TTSComparisonStatus.FAILED.value
                comp.error_message = f"Evaluation failed: {str(exc)[:400]}"
                db.commit()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()


@celery_app.task(name="generate_tts_report_pdf", bind=True, max_retries=1)
def generate_tts_report_pdf_task(self, report_job_id: str):
    """Generate a Voice Playground PDF report and store it in S3."""
    from app.models.database import (
        TTSComparison,
        TTSSample,
        TTSReportJob,
        TTSReportJobStatus,
    )
    from app.services.s3_service import s3_service
    from app.services.voice_playground_report_service import voice_playground_report_service

    db = SessionLocal()
    try:
        report_job = db.query(TTSReportJob).filter(TTSReportJob.id == UUID(report_job_id)).first()
        if not report_job:
            logger.error(f"[TTS Report] Job {report_job_id} not found")
            return {"error": "report_job_not_found"}

        comparison = (
            db.query(TTSComparison)
            .filter(
                TTSComparison.id == report_job.comparison_id,
                TTSComparison.organization_id == report_job.organization_id,
            )
            .first()
        )
        if not comparison:
            report_job.status = TTSReportJobStatus.FAILED.value
            report_job.error_message = "Comparison not found"
            db.commit()
            return {"error": "comparison_not_found"}

        report_job.status = TTSReportJobStatus.PROCESSING.value
        report_job.celery_task_id = self.request.id
        db.commit()

        samples = (
            db.query(TTSSample)
            .filter(TTSSample.comparison_id == comparison.id)
            .order_by(TTSSample.run_index, TTSSample.sample_index)
            .all()
        )

        payload = voice_playground_report_service.build_payload(comparison, samples)
        pdf_bytes = voice_playground_report_service.render_pdf(payload)

        report_filename = (
            f"voice-playground-report-{comparison.simulation_id or str(comparison.id)[:8]}.pdf"
        )
        s3_key = (
            f"{s3_service.prefix}organizations/{report_job.organization_id}/voicePlayground/"
            f"{comparison.id}/reports/{report_job.id}.pdf"
        )
        s3_service.upload_file_by_key(
            file_content=pdf_bytes,
            key=s3_key,
            content_type="application/pdf",
        )

        report_job.status = TTSReportJobStatus.COMPLETED.value
        report_job.filename = report_filename
        report_job.s3_key = s3_key
        report_job.error_message = None
        db.commit()

        return {"status": "completed", "s3_key": s3_key}
    except Exception as exc:
        logger.error(f"[TTS Report] Task failed: {exc}", exc_info=True)
        try:
            report_job = db.query(TTSReportJob).filter(TTSReportJob.id == UUID(report_job_id)).first()
            if report_job:
                report_job.status = TTSReportJobStatus.FAILED.value
                report_job.error_message = str(exc)[:500]
                db.commit()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()
