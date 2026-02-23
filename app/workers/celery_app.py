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
        
        logger.info(f"[EvaluatorResult {result.result_id}] Starting processing task (Celery task: {self.request.id})")
        logger.info(f"[EvaluatorResult {result.result_id}] Current status: {result.status}")
        logger.info(f"[EvaluatorResult {result.result_id}] Audio S3 key: {result.audio_s3_key}")
        logger.info(f"[EvaluatorResult {result.result_id}] Has existing transcription: {bool(result.transcription)}")
        logger.info(f"[EvaluatorResult {result.result_id}] Has call_data: {bool(result.call_data)}")
        
        # Update Celery task ID
        result.celery_task_id = self.request.id
        db.commit()
        
        # Check if transcript is already available (from provider call_data, or from a previous run)
        has_existing_transcript = bool(result.transcription)
        
        try:
            # Step 1: Verify we have either audio S3 key OR existing transcript
            logger.info(f"[EvaluatorResult {result.result_id}] Step 1: Verifying data source")
            if not result.audio_s3_key and not has_existing_transcript:
                raise ValueError("No audio S3 key or existing transcript found")
            
            if has_existing_transcript:
                logger.info(f"[EvaluatorResult {result.result_id}] ✓ Existing transcript found ({len(result.transcription)} chars)")
            elif result.audio_s3_key:
                logger.info(f"[EvaluatorResult {result.result_id}] ✓ Audio S3 key verified: {result.audio_s3_key}")
            
            # Step 2: Get evaluator and related entities for context
            logger.info(f"[EvaluatorResult {result.result_id}] Step 2: Loading evaluator and context data")
            
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
            
            logger.info(f"[EvaluatorResult {result.result_id}] ✓ Context loaded - Evaluator: {evaluator.evaluator_id if evaluator else 'None'}, Custom: {is_custom_evaluator}, Agent: {agent.name if agent else 'N/A'}, Persona: {persona.name if persona else 'None'}, Scenario: {scenario.name if scenario else 'None'}")
            
            # Step 3: Get or create transcription
            # Check if organization has configured AI providers (needed for evaluation even if skipping transcription)
            ai_providers = db.query(AIProvider).filter(
                AIProvider.organization_id == result.organization_id,
                AIProvider.is_active == True
            ).all()
            
            if has_existing_transcript:
                # Skip transcription - use existing transcript (from provider, previous run, or manual upload)
                logger.info(f"[EvaluatorResult {result.result_id}] Step 3: SKIPPING transcription (existing transcript found)")
                
                transcription = result.transcription
                speaker_segments = result.speaker_segments or []
                transcription_time = 0.0
                
                logger.info(f"[EvaluatorResult {result.result_id}] ✓ Using existing transcript: {len(transcription)} characters")
                logger.info(f"[EvaluatorResult {result.result_id}] ✓ Using existing speaker segments: {len(speaker_segments)} segments")
                
                if result.call_data:
                    provider_platform = result.provider_platform or "unknown"
                    logger.info(f"[EvaluatorResult {result.result_id}] Transcript source: {provider_platform} call_data")
                else:
                    logger.info(f"[EvaluatorResult {result.result_id}] Transcript source: previous transcription")
            else:
                # Transcribe audio using TranscriptionService
                logger.info(f"[EvaluatorResult {result.result_id}] Step 3: Starting transcription from audio")
                
                # Update status to TRANSCRIBING
                result.status = EvaluatorResultStatus.TRANSCRIBING.value
                db.commit()
                logger.info(f"[EvaluatorResult {result.result_id}] Status updated: QUEUED -> TRANSCRIBING")
                
                # Determine transcription model - check for AI Provider configuration
                # Default to OpenAI Whisper, but can be extended to other providers
                stt_provider = ModelProvider.OPENAI
                stt_model = "whisper-1"  # OpenAI Whisper API model
                
                # Prefer OpenAI for transcription, but can be extended
                openai_provider = next((p for p in ai_providers if provider_matches(p.provider, ModelProvider.OPENAI)), None)
                if not openai_provider:
                    logger.warning(f"[EvaluatorResult {result.result_id}] No OpenAI provider found, using default whisper-1")
                else:
                    logger.info(f"[EvaluatorResult {result.result_id}] Using OpenAI provider for transcription")
                
                transcription_start_time = time.time()
                logger.info(f"[EvaluatorResult {result.result_id}] Calling transcription service with model: {stt_model}")
                
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
                
                logger.info(f"[EvaluatorResult {result.result_id}] ✓ Transcription completed in {transcription_time:.2f}s")
                logger.info(f"[EvaluatorResult {result.result_id}] Transcription length: {len(transcription)} characters")
                logger.info(f"[EvaluatorResult {result.result_id}] Speaker segments: {len(speaker_segments)} segments detected")
                logger.debug(f"[EvaluatorResult {result.result_id}] Transcription preview: {transcription[:200]}...")
                
                result.transcription = transcription
                result.speaker_segments = speaker_segments if speaker_segments else None
                db.commit()
            
            # Initialize evaluation_time for potential error handling
            evaluation_time = None
            
            # Step 4: Get enabled metrics for the organization
            logger.info(f"[EvaluatorResult {result.result_id}] Step 4: Loading enabled metrics")
            enabled_metrics = db.query(Metric).filter(
                Metric.organization_id == result.organization_id,
                Metric.enabled == True
            ).all()
            
            logger.info(f"[EvaluatorResult {result.result_id}] ✓ Found {len(enabled_metrics)} enabled metrics")
            for metric in enabled_metrics:
                metric_type_val = metric.metric_type.value if hasattr(metric.metric_type, 'value') else metric.metric_type
                logger.debug(f"[EvaluatorResult {result.result_id}]   - {metric.name} ({metric_type_val})")
            
            # Step 5: Evaluate against enabled metrics using LLM
            metric_scores = {}
            
            if enabled_metrics and transcription:
                # Update status to EVALUATING
                result.status = EvaluatorResultStatus.EVALUATING.value
                db.commit()
                logger.info(f"[EvaluatorResult {result.result_id}] Status updated: TRANSCRIBING -> EVALUATING")
                logger.info(f"[EvaluatorResult {result.result_id}] Step 5: Starting metric evaluation")
                # Build metric key mapping for later use
                metric_key_map = {}  # metric_key -> metric object
                for metric in enabled_metrics:
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
                for metric in enabled_metrics:
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
                for metric in enabled_metrics:
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
                        # Use the evaluator's configured model
                        if isinstance(evaluator_llm_provider, str):
                            llm_provider = ModelProvider(evaluator_llm_provider.lower())
                        else:
                            llm_provider = evaluator_llm_provider
                        llm_model = evaluator_llm_model
                        logger.info(f"[EvaluatorResult {result.result_id}] Using evaluator-configured model: {llm_provider.value}/{llm_model}")
                    else:
                        # Fallback: pick the first available AI provider
                        llm_provider = ModelProvider.OPENAI
                        llm_model = "gpt-4o"
                        logger.info(f"[EvaluatorResult {result.result_id}] No evaluator model configured, using default: {llm_provider.value}/{llm_model}")
                    
                    # Verify the chosen provider is configured for this organization
                    chosen_provider = next((p for p in ai_providers if provider_matches(p.provider, llm_provider)), None)
                    if not chosen_provider:
                        logger.warning(f"[EvaluatorResult {result.result_id}] Provider {llm_provider.value} not configured, evaluation may fail")
                    else:
                        logger.info(f"[EvaluatorResult {result.result_id}] Using {llm_provider.value} provider with model: {llm_model}")
                    
                    logger.info(f"[EvaluatorResult {result.result_id}] Building evaluation prompt with {len(enabled_metrics)} metrics")
                    logger.debug(f"[EvaluatorResult {result.result_id}] Evaluation prompt length: {len(evaluation_prompt)} characters")
                    
                    # Build the list of exact metric keys for system message
                    exact_keys = [metric.name.lower().replace(" ", "_") for metric in enabled_metrics]
                    
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
                    logger.info(f"[EvaluatorResult {result.result_id}] Calling LLM service for evaluation...")
                    
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
                    logger.info(f"[EvaluatorResult {result.result_id}] ✓ LLM evaluation completed in {evaluation_time:.2f}s")
                    logger.debug(f"[EvaluatorResult {result.result_id}] LLM response preview: {llm_result.get('text', '')[:200]}...")
                    
                    # Parse LLM response
                    logger.info(f"[EvaluatorResult {result.result_id}] Parsing LLM response")
                    response_text = llm_result["text"].strip()
                    
                    # Try to extract JSON from response (handle cases where LLM adds markdown formatting)
                    if response_text.startswith("```json"):
                        response_text = response_text.replace("```json", "").replace("```", "").strip()
                        logger.debug(f"[EvaluatorResult {result.result_id}] Removed markdown JSON wrapper")
                    elif response_text.startswith("```"):
                        response_text = response_text.replace("```", "").strip()
                        logger.debug(f"[EvaluatorResult {result.result_id}] Removed markdown code block wrapper")
                    
                    try:
                        evaluation_data = json.loads(response_text)
                        logger.info(f"[EvaluatorResult {result.result_id}] ✓ Successfully parsed JSON response")
                    except json.JSONDecodeError as e:
                        logger.warning(f"[EvaluatorResult {result.result_id}] JSON parsing failed, attempting regex extraction: {e}")
                        # If JSON parsing fails, try to extract JSON object from text
                        json_match = re.search(r'\{[\s\S]*\}', response_text)
                        if json_match:
                            try:
                                evaluation_data = json.loads(json_match.group())
                                logger.info(f"[EvaluatorResult {result.result_id}] ✓ Extracted JSON using regex")
                            except json.JSONDecodeError:
                                raise ValueError("Could not parse extracted JSON")
                        else:
                            raise ValueError("Could not parse LLM response as JSON")
                    
                    # Handle nested response formats (e.g., {"metrics": {...}} or {"score": ..., "comments": ...})
                    logger.info(f"[EvaluatorResult {result.result_id}] Normalizing LLM response format")
                    logger.debug(f"[EvaluatorResult {result.result_id}] Raw evaluation_data keys: {list(evaluation_data.keys())}")
                    
                    # If response has a "metrics" wrapper, unwrap it
                    if "metrics" in evaluation_data and isinstance(evaluation_data["metrics"], dict):
                        evaluation_data = evaluation_data["metrics"]
                        logger.debug(f"[EvaluatorResult {result.result_id}] Unwrapped 'metrics' object")
                    
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
                    
                    # Map LLM response to metric scores with fuzzy matching
                    logger.info(f"[EvaluatorResult {result.result_id}] Mapping LLM response to metric scores")
                    response_keys = list(evaluation_data.keys())
                    logger.debug(f"[EvaluatorResult {result.result_id}] Response keys: {response_keys}")
                    
                    for metric in enabled_metrics:
                        metric_key = metric.name.lower().replace(" ", "_")
                        m_type = metric.metric_type.value if hasattr(metric.metric_type, 'value') else metric.metric_type
                        
                        # Try exact key first
                        raw_score = evaluation_data.get(metric_key)
                        
                        # If not found, try fuzzy matching
                        if raw_score is None:
                            matched_key = find_matching_key(metric.name, response_keys)
                            if matched_key:
                                raw_score = evaluation_data.get(matched_key)
                                logger.debug(f"[EvaluatorResult {result.result_id}]   Fuzzy matched '{metric.name}' -> '{matched_key}'")
                        
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
                        logger.debug(f"[EvaluatorResult {result.result_id}]   - {metric.name}: {score} (raw: {raw_score})")
                    
                    # Log summary of successful evaluations
                    successful = sum(1 for m in metric_scores.values() if m.get("value") is not None)
                    logger.info(f"[EvaluatorResult {result.result_id}] ✓ Successfully evaluated {successful}/{len(metric_scores)} metrics")
                        
                except Exception as e:
                    # Use str() to avoid format issues with curly braces in error messages
                    error_msg = str(e).replace("{", "{{").replace("}", "}}")
                    logger.error(f"[EvaluatorResult {result.result_id}] ✗ LLM evaluation failed: {error_msg}", exc_info=True)
                    # If LLM evaluation fails, mark metrics as None but don't fail the whole task
                    for metric in enabled_metrics:
                        m_type = metric.metric_type.value if hasattr(metric.metric_type, 'value') else metric.metric_type
                        metric_scores[str(metric.id)] = {
                            "value": None,
                            "type": m_type.lower() if isinstance(m_type, str) else m_type,
                            "metric_name": metric.name,
                            "error": str(e)
                        }
                    logger.warning(f"[EvaluatorResult {result.result_id}] Marked {len(enabled_metrics)} metrics as failed")
            else:
                if not enabled_metrics:
                    logger.warning(f"[EvaluatorResult {result.result_id}] No enabled metrics found, skipping evaluation")
                if not transcription:
                    logger.warning(f"[EvaluatorResult {result.result_id}] No transcription available, skipping evaluation")
            
            # Update status to COMPLETED
            result.metric_scores = metric_scores
            result.status = EvaluatorResultStatus.COMPLETED.value
            db.commit()
            
            total_time = time.time() - task_start_time
            logger.info(f"[EvaluatorResult {result.result_id}] Status updated: EVALUATING -> COMPLETED")
            logger.info(f"[EvaluatorResult {result.result_id}] ✓ Processing completed successfully in {total_time:.2f}s")
            logger.info(f"[EvaluatorResult {result.result_id}] Summary - Transcription: {len(transcription) if transcription else 0} chars, Metrics: {len(metric_scores)}")
            
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
            logger.error(f"[EvaluatorResult {result.result_id}] ✗ Processing failed: {e}", exc_info=True)
            result.status = EvaluatorResultStatus.FAILED.value
            result.error_message = str(e)
            db.commit()
            logger.error(f"[EvaluatorResult {result.result_id}] Status updated: -> FAILED")
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
        
        logger.info(
            f"[RunEvaluator {evaluator.evaluator_id}] Starting task "
            f"(Celery task: {self.request.id}, Result: {result.result_id})"
        )
        logger.info(f"[RunEvaluator {evaluator.evaluator_id}] Current status: {result.status}")
        
        # Update Celery task ID and ensure status is QUEUED (should already be)
        result.celery_task_id = self.request.id
        if result.status != EvaluatorResultStatus.QUEUED.value:
            logger.warning(f"[RunEvaluator {evaluator.evaluator_id}] Status was {result.status}, expected QUEUED")
        db.commit()
        logger.info(f"[RunEvaluator {evaluator.evaluator_id}] Task ID updated, proceeding with bridge")
        
        # Check if agent has both voice_bundle_id and voice_ai_integration_id
        has_voice_bundle = agent.voice_bundle_id is not None
        has_voice_ai_integration = agent.voice_ai_integration_id is not None and agent.voice_ai_agent_id is not None
        
        logger.info(
            f"[RunEvaluator {evaluator.evaluator_id}] Agent configuration check: "
            f"has_voice_bundle={has_voice_bundle}, has_voice_ai_integration={has_voice_ai_integration}"
        )
        
        if has_voice_bundle and has_voice_ai_integration:
            # Use bridge service to connect test agent to Voice AI agent
            logger.info(
                f"[RunEvaluator {evaluator.evaluator_id}] "
                f"Agent has both voice_bundle and voice_ai_integration, using bridge service"
            )
            
            try:
                # Update status immediately to show we're starting the bridge
                result.status = EvaluatorResultStatus.CALL_INITIATING.value
                result.call_event = "task_started"
                db.commit()
                logger.info(f"[RunEvaluator {evaluator.evaluator_id}] ✅ Status updated to CALL_INITIATING")
                
                # Run async bridge function
                logger.info(f"[RunEvaluator {evaluator.evaluator_id}] Setting up async event loop...")
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    logger.info(f"[RunEvaluator {evaluator.evaluator_id}] Event loop was closed, creating new one")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                logger.info(f"[RunEvaluator {evaluator.evaluator_id}] Calling bridge service...")
                bridge_result = loop.run_until_complete(
                    test_agent_bridge_service.bridge_test_agent_to_voice_agent(
                        evaluator_id=evaluator_uuid,
                        evaluator_result_id=result_uuid,
                        organization_id=evaluator.organization_id,
                        db=db,
                    )
                )
                
                logger.info(
                    f"[RunEvaluator {evaluator.evaluator_id}] "
                    f"Bridge service completed: {bridge_result.get('call_id')}"
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
                logger.error(
                    f"[RunEvaluator {evaluator.evaluator_id}] "
                    f"❌ Bridge service error: {bridge_error}",
                    exc_info=True
                )
                result.status = EvaluatorResultStatus.FAILED.value
                result.error_message = str(bridge_error)
                result.call_event = "bridge_error"
                db.commit()
                raise
        
        elif has_voice_bundle:
            # Only voice bundle - use standard voice agent flow
            logger.info(
                f"[RunEvaluator {evaluator.evaluator_id}] "
                f"Agent has voice_bundle only, using standard flow"
            )
            # This would trigger the standard voice agent WebSocket connection
            # For now, mark as needing implementation
            result.status = EvaluatorResultStatus.FAILED.value
            result.error_message = "Standard voice agent flow not yet implemented for evaluator runs"
            db.commit()
            return {"error": "Standard flow not implemented"}
        
        else:
            # No voice bundle configured
            logger.error(
                f"[RunEvaluator {evaluator.evaluator_id}] "
                f"❌ Agent does not have required configuration: "
                f"voice_bundle_id={has_voice_bundle}, voice_ai_integration={has_voice_ai_integration}"
            )
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
    from app.services.tts_service import tts_service

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

        failed_count = 0
        for sample in samples:
            try:
                sample.status = TTSSampleStatus.GENERATING.value
                db.commit()

                provider_enum = ModelProvider(sample.provider)
                audio_bytes, latency_ms = tts_service.synthesize_timed(
                    text=sample.text,
                    tts_provider=provider_enum,
                    tts_model=sample.model,
                    organization_id=comp.organization_id,
                    db=db,
                    voice=sample.voice_id,
                )

                from app.services.s3_service import s3_service

                s3_key = s3_service.upload_file_by_key(
                    file_content=audio_bytes,
                    key=f"{s3_service.prefix}organizations/{comp.organization_id}/voicePlayground/{comp.id}/{sample.id}.mp3",
                )

                # Estimate duration from file size (MP3 ~128kbps)
                duration_est = len(audio_bytes) / (128000 / 8) if audio_bytes else None

                sample.audio_s3_key = s3_key
                sample.latency_ms = round(latency_ms, 1)
                sample.duration_seconds = round(duration_est, 2) if duration_est else None
                sample.status = TTSSampleStatus.COMPLETED.value
                db.commit()

                logger.info(
                    f"[TTS Generate] Sample {sample.id} done – "
                    f"{sample.provider}/{sample.voice_name} latency={latency_ms:.0f}ms"
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


@celery_app.task(name="evaluate_tts_comparison", bind=True, max_retries=1)
def evaluate_tts_comparison_task(self, comparison_id: str):
    """
    Download each completed sample from S3 and run qualitative voice
    metrics (MOS, Valence, Arousal, Prosody).
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
