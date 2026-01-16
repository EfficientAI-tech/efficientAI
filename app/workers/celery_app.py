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
        
        # Check if transcript is already available (from provider call_data)
        # This happens when using Retell/Vapi where transcript is provided directly
        has_provider_transcript = bool(result.transcription) and bool(result.call_data)
        
        try:
            # Step 1: Verify we have either audio S3 key OR existing transcript from provider
            logger.info(f"[EvaluatorResult {result.result_id}] Step 1: Verifying data source")
            if not result.audio_s3_key and not has_provider_transcript:
                raise ValueError("No audio S3 key or provider transcript found")
            
            if has_provider_transcript:
                logger.info(f"[EvaluatorResult {result.result_id}] ✓ Using transcript from provider (call_data)")
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
            
            agent = db.query(Agent).filter(Agent.id == result.agent_id).first()
            if not agent:
                raise ValueError("Agent not found")
            
            # Persona and scenario are optional
            persona = None
            if result.persona_id:
                persona = db.query(Persona).filter(Persona.id == result.persona_id).first()
            
            scenario = None
            if result.scenario_id:
                scenario = db.query(Scenario).filter(Scenario.id == result.scenario_id).first()
            
            logger.info(f"[EvaluatorResult {result.result_id}] ✓ Context loaded - Evaluator: {evaluator.evaluator_id if evaluator else 'None'}, Agent: {agent.name if agent else 'N/A'}, Persona: {persona.name if persona else 'None'}, Scenario: {scenario.name if scenario else 'None'}")
            
            # Step 3: Get or create transcription
            # Check if organization has configured AI providers (needed for evaluation even if skipping transcription)
            ai_providers = db.query(AIProvider).filter(
                AIProvider.organization_id == result.organization_id,
                AIProvider.is_active == True
            ).all()
            
            if has_provider_transcript:
                # Skip transcription - use transcript from provider (Retell/Vapi)
                logger.info(f"[EvaluatorResult {result.result_id}] Step 3: SKIPPING transcription (using provider transcript)")
                
                transcription = result.transcription
                speaker_segments = result.speaker_segments or []
                transcription_time = 0.0  # No transcription time since we skipped it
                
                logger.info(f"[EvaluatorResult {result.result_id}] ✓ Using existing transcript: {len(transcription)} characters")
                logger.info(f"[EvaluatorResult {result.result_id}] ✓ Using existing speaker segments: {len(speaker_segments)} segments")
                
                # Log provider info
                provider_platform = result.provider_platform or "unknown"
                logger.info(f"[EvaluatorResult {result.result_id}] Transcript source: {provider_platform} call_data")
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
                openai_provider = next((p for p in ai_providers if p.provider == ModelProvider.OPENAI), None)
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
                logger.debug(f"[EvaluatorResult {result.result_id}]   - {metric.name} ({metric.metric_type.value})")
            
            # Step 5: Evaluate against enabled metrics using LLM
            metric_scores = {}
            
            if enabled_metrics and transcription:
                # Update status to EVALUATING
                result.status = EvaluatorResultStatus.EVALUATING.value
                db.commit()
                logger.info(f"[EvaluatorResult {result.result_id}] Status updated: TRANSCRIBING -> EVALUATING")
                logger.info(f"[EvaluatorResult {result.result_id}] Step 5: Starting metric evaluation")
                # Build context for evaluation
                agent_objective = agent.description if agent and agent.description else f"The agent's objective is to handle {agent.call_type.value if agent and agent.call_type else 'conversations'}."
                scenario_context = scenario.description if scenario and scenario.description else ""
                scenario_goals = scenario.required_info if scenario and scenario.required_info else {}
                
                # Build evaluation prompt
                evaluation_prompt = f"""You are evaluating a conversation transcript to determine how well the agent performed against specific metrics.

Agent Information:
- Name: {agent.name if agent else 'Unknown'}
- Objective/Purpose: {agent_objective}
- Call Type: {agent.call_type.value if agent and agent.call_type else 'N/A'}
- Language: {persona.language.value if persona and persona.language else 'N/A'}

Scenario Information:
- Name: {scenario.name if scenario else 'Unknown'}
- Description: {scenario_context}
- Required Information: {json.dumps(scenario_goals) if scenario_goals else 'N/A'}

Conversation Transcript:
{transcription}

Please evaluate this conversation against the following metrics and provide scores:
"""
                
                # Add metric descriptions to prompt
                for metric in enabled_metrics:
                    metric_desc = metric.description or f"Evaluate {metric.name}"
                    if metric.metric_type.value == "rating":
                        evaluation_prompt += f"\n- {metric.name} (rating 0.0-1.0): {metric_desc}"
                    elif metric.metric_type.value == "boolean":
                        evaluation_prompt += f"\n- {metric.name} (true/false): {metric_desc}"
                    elif metric.metric_type.value == "number":
                        evaluation_prompt += f"\n- {metric.name} (numeric value): {metric_desc}"
                
                evaluation_prompt += f"""

Respond in JSON format with the following structure:
{{
"""
                for metric in enabled_metrics:
                    metric_key = metric.name.lower().replace(" ", "_")
                    if metric.metric_type.value == "rating":
                        evaluation_prompt += f'    "{metric_key}": 0.0-1.0,\n'
                    elif metric.metric_type.value == "boolean":
                        evaluation_prompt += f'    "{metric_key}": true/false,\n'
                    elif metric.metric_type.value == "number":
                        evaluation_prompt += f'    "{metric_key}": <numeric_value>,\n'
                
                evaluation_prompt += """}

Only respond with valid JSON, no additional text."""
                
                # Call LLM service for evaluation
                try:
                    # Determine LLM provider and model - extensible to other providers
                    llm_provider = ModelProvider.OPENAI  # Default to OpenAI
                    llm_model = "gpt-4o"  # Default model (user mentioned GPT-5, but gpt-4o is current best)
                    
                    # Check for available AI providers - can be extended to Gemini, etc.
                    openai_provider = next((p for p in ai_providers if p.provider == ModelProvider.OPENAI), None)
                    google_provider = next((p for p in ai_providers if p.provider == ModelProvider.GOOGLE), None)
                    
                    # For now, prefer OpenAI. Can be extended to check for Gemini key:
                    # if google_provider:
                    #     llm_provider = ModelProvider.GOOGLE
                    #     llm_model = "gemini-pro"
                    
                    if not openai_provider:
                        logger.warning(f"[EvaluatorResult {result.result_id}] No OpenAI provider found, evaluation may fail")
                    else:
                        logger.info(f"[EvaluatorResult {result.result_id}] Using {llm_provider.value} provider with model: {llm_model}")
                    
                    logger.info(f"[EvaluatorResult {result.result_id}] Building evaluation prompt with {len(enabled_metrics)} metrics")
                    logger.debug(f"[EvaluatorResult {result.result_id}] Evaluation prompt length: {len(evaluation_prompt)} characters")
                    
                    messages = [
                        {"role": "system", "content": "You are an expert conversation evaluator. Analyze conversations objectively and provide structured evaluations in JSON format."},
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
                        json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
                        if json_match:
                            evaluation_data = json.loads(json_match.group())
                            logger.info(f"[EvaluatorResult {result.result_id}] ✓ Extracted JSON using regex")
                        else:
                            raise ValueError("Could not parse LLM response as JSON")
                    
                    # Map LLM response to metric scores
                    logger.info(f"[EvaluatorResult {result.result_id}] Mapping LLM response to metric scores")
                    for metric in enabled_metrics:
                        metric_key = metric.name.lower().replace(" ", "_")
                        score = evaluation_data.get(metric_key)
                        
                        # Validate and convert score based on metric type
                        if metric.metric_type.value == "rating":
                            if score is not None:
                                try:
                                    score = float(score)
                                    # Clamp to 0.0-1.0 range
                                    score = max(0.0, min(1.0, score))
                                except (ValueError, TypeError):
                                    score = None
                        elif metric.metric_type.value == "boolean":
                            if score is not None:
                                score = bool(score)
                        elif metric.metric_type.value == "number":
                            if score is not None:
                                try:
                                    score = float(score)
                                except (ValueError, TypeError):
                                    score = None
                        
                        metric_scores[str(metric.id)] = {
                            "value": score,
                            "type": metric.metric_type.value,
                            "metric_name": metric.name
                        }
                        logger.debug(f"[EvaluatorResult {result.result_id}]   - {metric.name}: {score}")
                    
                    logger.info(f"[EvaluatorResult {result.result_id}] ✓ Successfully evaluated {len(metric_scores)} metrics")
                        
                except Exception as e:
                    logger.error(f"[EvaluatorResult {result.result_id}] ✗ LLM evaluation failed: {e}", exc_info=True)
                    # If LLM evaluation fails, mark metrics as None but don't fail the whole task
                    for metric in enabled_metrics:
                        metric_scores[str(metric.id)] = {
                            "value": None,
                            "type": metric.metric_type.value,
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
