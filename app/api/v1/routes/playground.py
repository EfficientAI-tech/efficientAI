"""
Playground API Routes
API endpoints for testing voice agents in the playground
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, List
from uuid import UUID
from pydantic import BaseModel
from loguru import logger
import random

from app.dependencies import get_db, get_organization_id, get_api_key
from app.models.database import (
    Agent,
    Integration,
    IntegrationPlatform,
    CallRecording,
    CallRecordingStatus,
    CallRecordingSource,
    EvaluatorResult,
    EvaluatorResultStatus,
)
from app.core.encryption import decrypt_api_key
from app.services.voice_providers import get_voice_provider
from app.utils.call_recordings import generate_unique_call_short_id

router = APIRouter(prefix="/playground", tags=["playground"])


def extract_transcript_from_call_data(call_data: Dict[str, Any], provider_platform: str) -> tuple:
    """
    Extract transcript and speaker segments from provider call_data.
    
    Args:
        call_data: Full call data from voice provider (Vapi/Retell)
        provider_platform: The provider platform ("vapi" or "retell")
        
    Returns:
        Tuple of (transcript_text, speaker_segments)
        - transcript_text: Plain text transcript
        - speaker_segments: List of segments with speaker labels
    """
    transcript_text = ""
    speaker_segments = []
    
    if not call_data:
        return transcript_text, speaker_segments
    
    provider_platform_lower = provider_platform.lower() if provider_platform else ""
    
    if provider_platform_lower == "vapi":
        # Vapi: transcript is in call_data["transcript"] or build from transcript_object
        transcript_text = call_data.get("transcript", "")
        
        # Get structured messages for speaker segments
        transcript_object = call_data.get("transcript_object", [])
        if not transcript_object:
            # Try messages array
            messages = call_data.get("messages", [])
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("message", "") or msg.get("content", "")
                
                if not content or role == "system":
                    continue
                
                # Map roles
                if role in ["bot", "assistant"]:
                    normalized_role = "agent"
                elif role == "user":
                    normalized_role = "user"
                else:
                    continue
                
                speaker_segments.append({
                    "speaker": "Agent" if normalized_role == "agent" else "User",
                    "text": content,
                    "start": msg.get("secondsFromStart", 0),
                    "end": msg.get("secondsFromStart", 0) + (msg.get("duration", 0) / 1000),
                })
        else:
            for entry in transcript_object:
                role = entry.get("role", "unknown")
                content = entry.get("content", "")
                
                if not content:
                    continue
                
                speaker_segments.append({
                    "speaker": "Agent" if role == "agent" else "User",
                    "text": content,
                    "start": entry.get("seconds_from_start", 0),
                    "end": entry.get("seconds_from_start", 0) + (entry.get("duration_ms", 0) / 1000),
                })
        
        # Build transcript text from segments if not available
        if not transcript_text and speaker_segments:
            transcript_text = "\n".join([
                f"{seg['speaker']}: {seg['text']}" for seg in speaker_segments
            ])
            
    elif provider_platform_lower == "retell":
        # Retell: transcript can be a string or list of objects
        transcript_raw = call_data.get("transcript", "")
        
        if isinstance(transcript_raw, str):
            transcript_text = transcript_raw
            # Parse transcript text into speaker segments if it has pattern like "Agent: text\nUser: text"
            lines = transcript_raw.split("\n") if transcript_raw else []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("Agent:") or line.startswith("agent:"):
                    speaker_segments.append({
                        "speaker": "Agent",
                        "text": line.split(":", 1)[1].strip() if ":" in line else line,
                        "start": 0,
                        "end": 0,
                    })
                elif line.startswith("User:") or line.startswith("user:"):
                    speaker_segments.append({
                        "speaker": "User",
                        "text": line.split(":", 1)[1].strip() if ":" in line else line,
                        "start": 0,
                        "end": 0,
                    })
        elif isinstance(transcript_raw, list):
            # Retell sometimes returns transcript as array of objects
            for item in transcript_raw:
                if isinstance(item, dict):
                    role = item.get("role", "")
                    content = item.get("content", "") or item.get("text", "")
                    
                    if not content:
                        continue
                    
                    speaker = "Agent" if role in ["agent", "assistant", "bot"] else "User"
                    speaker_segments.append({
                        "speaker": speaker,
                        "text": content,
                        "start": item.get("start_time", 0) or item.get("timestamp", 0),
                        "end": item.get("end_time", 0),
                    })
            
            # Build transcript text from segments
            transcript_text = "\n".join([
                f"{seg['speaker']}: {seg['text']}" for seg in speaker_segments
            ])
    
    return transcript_text, speaker_segments


def generate_unique_result_id(db: Session) -> str:
    """Generate a unique 6-digit result ID for EvaluatorResult."""
    max_attempts = 100
    for _ in range(max_attempts):
        candidate_id = f"{random.randint(100000, 999999)}"
        existing = db.query(EvaluatorResult).filter(EvaluatorResult.result_id == candidate_id).first()
        if not existing:
            return candidate_id
    raise ValueError("Failed to generate unique result ID")


def poll_call_metrics(
    call_recording_id: UUID,
    provider_call_id: str,
    provider_platform: str,
    integration_api_key: str,
    max_attempts: int = 60,
    poll_interval: int = 5
):
    """
    Background task to poll for call metrics from the provider.
    After call is complete, creates an EvaluatorResult and triggers metric evaluation.
    
    Args:
        call_recording_id: The CallRecording database ID
        provider_call_id: The provider's call_id (e.g., Retell call_id)
        provider_platform: The provider platform (e.g., "retell")
        integration_api_key: The decrypted API key for the provider
        max_attempts: Maximum number of polling attempts
        poll_interval: Seconds between polling attempts
    """
    import time
    from app.database import SessionLocal
    from app.services.voice_providers import get_voice_provider
    
    db = SessionLocal()
    call_complete = False
    call_metrics = None
    
    try:
        call_recording = db.query(CallRecording).filter(CallRecording.id == call_recording_id).first()
        if not call_recording:
            return
        
        if not provider_call_id or provider_call_id == "None":
            return

        # Get the appropriate voice provider
        try:
            provider_class = get_voice_provider(provider_platform)
            provider = provider_class(api_key=integration_api_key)
        except ValueError:
            return
        
        # Poll for call metrics
        for attempt in range(max_attempts):
            try:
                # Wait before polling (except first attempt)
                if attempt > 0:
                    time.sleep(poll_interval)
                
                # Retrieve call metrics
                if hasattr(provider, "retrieve_call_metrics"):
                    call_metrics = provider.retrieve_call_metrics(provider_call_id)
                else:
                    # For other providers, implement similar method
                    continue
                
                # Update the call recording with metrics
                call_recording.call_data = call_metrics
                call_recording.status = CallRecordingStatus.UPDATED
                db.commit()
                db.refresh(call_recording)
                
                # Check if call is complete (has end_timestamp or call_status indicates completion)
                call_status = call_metrics.get("call_status", "")
                end_timestamp = call_metrics.get("end_timestamp")
                
                # If call is complete, stop polling
                if end_timestamp or call_status in ["ended", "completed", "failed", "end-of-call-report"]:
                    call_complete = True
                    break
                    
            except Exception as e:
                # Log error but continue polling
                logger.warning(f"[Poll Call Metrics] Error on attempt {attempt + 1}: {str(e)}")
                # If it's a 404 or similar, the call might not exist yet, continue polling
                continue
        
        # After polling is complete, create EvaluatorResult and trigger evaluation
        if call_complete and call_metrics and call_recording.agent_id:
            try:
                logger.info(f"[Poll Call Metrics] Call complete, creating EvaluatorResult for call {provider_call_id}")
                
                # Extract transcript and speaker segments from call_data
                transcript_text, speaker_segments = extract_transcript_from_call_data(
                    call_metrics, 
                    provider_platform
                )
                
                if not transcript_text:
                    logger.warning(f"[Poll Call Metrics] No transcript found in call_data for call {provider_call_id}")
                
                # Get agent info for naming
                agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()
                result_name = f"Voice AI Call - {agent.name}" if agent else "Voice AI Call"
                
                # Calculate duration
                duration_seconds = call_metrics.get("duration_seconds", 0)
                if not duration_seconds:
                    # Try to calculate from timestamps
                    start_ts = call_metrics.get("start_timestamp")
                    end_ts = call_metrics.get("end_timestamp")
                    if start_ts and end_ts:
                        try:
                            from dateutil import parser
                            start_time = parser.parse(start_ts)
                            end_time = parser.parse(end_ts)
                            duration_seconds = (end_time - start_time).total_seconds()
                        except Exception:
                            pass
                
                # Generate unique result ID
                result_id = generate_unique_result_id(db)
                
                # Create EvaluatorResult
                evaluator_result = EvaluatorResult(
                    result_id=result_id,
                    organization_id=call_recording.organization_id,
                    evaluator_id=None,  # No evaluator for playground calls
                    agent_id=call_recording.agent_id,
                    persona_id=None,  # No persona for Voice AI agent playground calls
                    scenario_id=None,  # No scenario for Voice AI agent playground calls
                    name=result_name,
                    duration_seconds=duration_seconds,
                    status=EvaluatorResultStatus.QUEUED.value,
                    audio_s3_key=None,  # Audio is in provider's storage, URL in call_data
                    transcription=transcript_text,
                    speaker_segments=speaker_segments if speaker_segments else None,
                    provider_call_id=provider_call_id,
                    provider_platform=provider_platform,
                    call_data=call_metrics,
                )
                db.add(evaluator_result)
                db.commit()
                db.refresh(evaluator_result)
                
                # Link the EvaluatorResult to CallRecording
                call_recording.evaluator_result_id = evaluator_result.id
                db.commit()
                
                logger.info(f"[Poll Call Metrics] Created EvaluatorResult {result_id} for call {provider_call_id}")
                
                # Trigger Celery task to process evaluator result (run metrics evaluation)
                try:
                    from app.workers.celery_app import process_evaluator_result_task
                    task = process_evaluator_result_task.delay(str(evaluator_result.id))
                    evaluator_result.celery_task_id = task.id
                    db.commit()
                    logger.info(f"[Poll Call Metrics] Triggered evaluation task {task.id} for result {result_id}")
                except Exception as task_error:
                    logger.error(f"[Poll Call Metrics] Failed to trigger Celery task: {task_error}")
                    # Mark the result as failed if we can't trigger the task
                    # But keep the transcript available for manual review
                    
            except Exception as e:
                logger.error(f"[Poll Call Metrics] Error creating EvaluatorResult: {str(e)}", exc_info=True)
        
    finally:
        db.close()


class CallRecordingUpdate(BaseModel):
    """Schema for updating a call recording."""
    provider_call_id: str


@router.put("/call-recordings/{call_short_id}", response_model=Dict[str, Any])
async def update_call_recording(
    call_short_id: str,
    update_data: CallRecordingUpdate,
    background_tasks: BackgroundTasks,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Update a call recording, typically to set the provider_call_id.
    Triggers polling.
    """
    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id
    ).first()
    
    if not call_recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call recording not found"
        )
    
    call_recording.provider_call_id = update_data.provider_call_id
    db.commit()
    db.refresh(call_recording)
    
    # Trigger polling if we have all info
    if call_recording.provider_platform:
        # Get integration api key
        agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()
        if agent and agent.voice_ai_integration_id:
            integration = db.query(Integration).filter(
                Integration.id == agent.voice_ai_integration_id
            ).first()
            
            if integration:
                try:
                    decrypted_api_key = decrypt_api_key(integration.api_key)
                    background_tasks.add_task(
                        poll_call_metrics,
                        call_recording.id,
                        call_recording.provider_call_id,
                        call_recording.provider_platform,
                        decrypted_api_key
                    )
                except:
                    pass
    
    return {
        "message": "Call recording updated", 
        "provider_call_id": call_recording.provider_call_id
    }


class WebCallCreate(BaseModel):
    """Schema for creating a web call."""
    agent_id: str  # UUID of the agent in our system
    metadata: Optional[Dict[str, Any]] = None
    retell_llm_dynamic_variables: Optional[Dict[str, Any]] = None
    custom_sip_headers: Optional[Dict[str, str]] = None


@router.post("/web-call", response_model=Dict[str, Any])
async def create_web_call(
    web_call_data: WebCallCreate,
    background_tasks: BackgroundTasks,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Create a web call with a voice AI agent.
    This endpoint handles the creation of web calls for different voice providers (Retell, Vapi, etc.)
    """
    try:
        # Get the agent
        agent_uuid = UUID(web_call_data.agent_id)
        agent = db.query(Agent).filter(
            Agent.id == agent_uuid,
            Agent.organization_id == organization_id
        ).first()
        
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found"
            )
        
        # Check if agent has voice AI integration
        if not agent.voice_ai_integration_id or not agent.voice_ai_agent_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent is not configured with a voice AI integration"
            )
        
        # Check if agent has web call enabled
        if agent.call_medium != "web_call":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent is not configured for web calls"
            )
        
        # Get the integration
        integration = db.query(Integration).filter(
            Integration.id == agent.voice_ai_integration_id,
            Integration.organization_id == organization_id,
            Integration.is_active == True
        ).first()
        
        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Integration not found or inactive"
            )
        
        # Decrypt API key
        try:
            decrypted_api_key = decrypt_api_key(integration.api_key)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to decrypt API key: {str(e)}"
            )
        
        # Get the appropriate voice provider
        try:
            provider_class = get_voice_provider(integration.platform)
            
            # For Vapi, pass the public_key as well (needed for web call creation)
            platform_value = integration.platform.value if hasattr(integration.platform, 'value') else integration.platform
            if platform_value.lower() == "vapi":
                provider = provider_class(api_key=decrypted_api_key, public_key=integration.public_key)
            else:
                provider = provider_class(api_key=decrypted_api_key)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        
        # Create the web call
        try:
            # Verify agent_id is present
            if not agent.voice_ai_agent_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Agent does not have a voice_ai_agent_id configured"
                )
            
            print(f"[Playground] Creating web call - Agent ID: {agent.id}, Retell Agent ID: {agent.voice_ai_agent_id}, Platform: {integration.platform}")
            
            # Build call parameters based on provider
            call_params = {
                "agent_id": agent.voice_ai_agent_id,
            }
            
            # Add optional parameters if provided
            if web_call_data.metadata:
                call_params["metadata"] = web_call_data.metadata
            if web_call_data.retell_llm_dynamic_variables:
                call_params["retell_llm_dynamic_variables"] = web_call_data.retell_llm_dynamic_variables
            
            # Note: custom_sip_headers is not supported by Retell, but may be supported by other providers
            # For now, we'll skip it for Retell. Other providers can handle it in their implementation.
            if integration.platform != "retell" and web_call_data.custom_sip_headers:
                call_params["custom_sip_headers"] = web_call_data.custom_sip_headers
            
            web_call_response = provider.create_web_call(**call_params)
            
            # Store call recording in database
            call_short_id = generate_unique_call_short_id(db)
            provider_call_id = web_call_response.get("call_id")
            
            call_recording = CallRecording(
                organization_id=organization_id,
                call_short_id=call_short_id,
                status=CallRecordingStatus.PENDING,
                source=CallRecordingSource.PLAYGROUND,
                call_data=web_call_response,  # Store initial response
                provider_call_id=provider_call_id,
                provider_platform=integration.platform,
                agent_id=agent.id
            )
            db.add(call_recording)
            db.commit()
            db.refresh(call_recording)
            
            # Start background task to poll for call metrics
            # Note: We need to pass the decrypted API key, but we should be careful with security
            # For now, we'll pass it to the background task
            # In production, you might want to store it temporarily or use a different approach
            if provider_call_id:
                background_tasks.add_task(
                    poll_call_metrics,
                    call_recording.id,
                    provider_call_id,
                    integration.platform,
                    decrypted_api_key
                )
            
            # Add call_short_id to response for frontend
            response = web_call_response.copy()
            response["call_short_id"] = call_short_id
            
            # For Vapi, include the public key in the response (needed for frontend SDK)
            platform_value = integration.platform.value if hasattr(integration.platform, 'value') else integration.platform
            if platform_value.lower() == "vapi" and integration.public_key:
                response["public_key"] = integration.public_key
            
            return response
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create web call: {str(e)}"
            )
            
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid agent ID: {str(e)}"
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        print(f"[Create Web Call] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/call-recordings", response_model=List[Dict[str, Any]])
async def list_call_recordings(
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    List all call recordings for the organization.
    Includes evaluator_result_id, evaluation status, and metric_scores if evaluation has been run.
    """
    call_recordings = db.query(CallRecording).filter(
        CallRecording.organization_id == organization_id,
        CallRecording.source == CallRecordingSource.PLAYGROUND,
    ).order_by(CallRecording.created_at.desc()).offset(skip).limit(limit).all()
    
    # Get evaluator result info for all linked results
    result_ids = [cr.evaluator_result_id for cr in call_recordings if cr.evaluator_result_id]
    result_info = {}
    if result_ids:
        results = db.query(EvaluatorResult).filter(EvaluatorResult.id.in_(result_ids)).all()
        result_info = {
            str(r.id): {
                "status": r.status,
                "metric_scores": r.metric_scores,
                "result_id": r.result_id,
            }
            for r in results
        }
    
    return [
        {
            "id": str(cr.id),
            "call_short_id": cr.call_short_id,
            "status": cr.status if cr.status else None,
            "provider_platform": cr.provider_platform,
            "provider_call_id": cr.provider_call_id,
            "agent_id": str(cr.agent_id) if cr.agent_id else None,
            "evaluator_result_id": str(cr.evaluator_result_id) if cr.evaluator_result_id else None,
            "evaluation_status": result_info.get(str(cr.evaluator_result_id), {}).get("status") if cr.evaluator_result_id else None,
            "metric_scores": result_info.get(str(cr.evaluator_result_id), {}).get("metric_scores") if cr.evaluator_result_id else None,
            "result_id": result_info.get(str(cr.evaluator_result_id), {}).get("result_id") if cr.evaluator_result_id else None,
            "created_at": cr.created_at.isoformat() if cr.created_at else None,
            "updated_at": cr.updated_at.isoformat() if cr.updated_at else None,
        }
        for cr in call_recordings
    ]


@router.get("/call-recordings/{call_short_id}", response_model=Dict[str, Any])
async def get_call_recording(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Get a specific call recording by its 6-digit short ID.
    Returns the full JSON data stored for the call and evaluation information.
    """
    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id,
        CallRecording.source == CallRecordingSource.PLAYGROUND,
    ).first()
    
    if not call_recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call recording not found"
        )
    
    # Get evaluator result info if available
    evaluation_info = None
    if call_recording.evaluator_result_id:
        evaluator_result = db.query(EvaluatorResult).filter(
            EvaluatorResult.id == call_recording.evaluator_result_id
        ).first()
        if evaluator_result:
            evaluation_info = {
                "id": str(evaluator_result.id),
                "result_id": evaluator_result.result_id,
                "status": evaluator_result.status,
                "metric_scores": evaluator_result.metric_scores,
                "transcription": evaluator_result.transcription,
            }
    
    return {
        "id": str(call_recording.id),
        "call_short_id": call_recording.call_short_id,
        "status": call_recording.status if call_recording.status else None,
        "provider_platform": call_recording.provider_platform,
        "provider_call_id": call_recording.provider_call_id,
        "agent_id": str(call_recording.agent_id) if call_recording.agent_id else None,
        "evaluator_result_id": str(call_recording.evaluator_result_id) if call_recording.evaluator_result_id else None,
        "evaluation": evaluation_info,
        "call_data": call_recording.call_data,  # Full JSON blob
        "created_at": call_recording.created_at.isoformat() if call_recording.created_at else None,
        "updated_at": call_recording.updated_at.isoformat() if call_recording.updated_at else None,
    }


@router.post("/call-recordings/{call_short_id}/refresh", response_model=Dict[str, Any])
async def refresh_call_recording(
    call_short_id: str,
    background_tasks: BackgroundTasks,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Manually trigger a refresh of call metrics for a specific call recording.
    """
    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id,
        CallRecording.source == CallRecordingSource.PLAYGROUND,
    ).first()
    
    if not call_recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call recording not found"
        )
    
    if not call_recording.provider_call_id or not call_recording.provider_platform:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Call recording does not have provider information"
        )
    
    # Get the integration to get the API key
    agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()
    if not agent or not agent.voice_ai_integration_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent or integration not found"
        )
    
    integration = db.query(Integration).filter(
        Integration.id == agent.voice_ai_integration_id,
        Integration.organization_id == organization_id
    ).first()
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )
    
    try:
        decrypted_api_key = decrypt_api_key(integration.api_key)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to decrypt API key: {str(e)}"
        )
    
    # Start background task to poll for call metrics
    background_tasks.add_task(
        poll_call_metrics,
        call_recording.id,
        call_recording.provider_call_id,
        call_recording.provider_platform,
        decrypted_api_key
    )
    
    return {"message": "Call recording refresh initiated"}


@router.delete("/call-recordings/{call_short_id}", response_model=Dict[str, Any])
async def delete_call_recording(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Delete a call recording by its 6-digit short ID.
    """
    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id
    ).first()
    
    if not call_recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call recording not found"
        )
    
    db.delete(call_recording)
    db.commit()
    
    return {"message": "Call recording deleted successfully"}

