"""
Playground API Routes
API endpoints for testing voice agents in the playground
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks, Form, File, UploadFile, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, List
from uuid import UUID
from pydantic import BaseModel
from loguru import logger
import random
import json
import uuid as _uuid
from datetime import datetime

from app.services.billing.flexprice_service import (
    record_playground_web_call_started,
    record_playground_websocket_session_started,
)
from app.database import get_db
from app.dependencies import get_organization_id, get_workspace_id, get_api_key
from app.models.database import (
    Agent,
    Integration,
    IntegrationPlatform,
    CallRecording,
    CallRecordingStatus,
    CallRecordingSource,
    EvaluatorResult,
    EvaluatorResultStatus,
    VoiceBundle,
    AIProvider,
    ModelProvider,
)
from app.core.encryption import decrypt_api_key
from app.services.voice_providers import get_voice_provider
from app.services.evaluators.evaluator_result_call_data import slim_call_data_for_evaluator_result
from app.utils.call_recordings import generate_unique_call_short_id

from app.services.evaluators.call_data_transcript import extract_transcript_from_call_data

router = APIRouter(prefix="/playground", tags=["playground"])


def _resolve_playground_audio_url(
    call_data: dict[str, Any],
    platform: str,
    *,
    stereo: bool = False,
) -> Optional[str]:
    artifact = call_data.get("artifact", {}) if isinstance(call_data.get("artifact"), dict) else {}
    recording = artifact.get("recording", {}) if isinstance(artifact.get("recording"), dict) else {}
    mono_recording = recording.get("mono", {}) if isinstance(recording.get("mono"), dict) else {}
    recording_urls = call_data.get("recording_urls", {}) if isinstance(call_data.get("recording_urls"), dict) else {}

    plat = (platform or "").lower()
    if plat == "vapi":
        from app.services.voice_providers.vapi_recording import extract_vapi_recording_url

        return extract_vapi_recording_url(call_data, stereo=stereo)

    return (
        call_data.get("recordingUrl")
        or call_data.get("stereoRecordingUrl")
        or artifact.get("recordingUrl")
        or artifact.get("stereoRecordingUrl")
        or mono_recording.get("combinedUrl")
        or recording_urls.get("combined_url")
        or recording_urls.get("stereo_url")
        or call_data.get("recording_url")
        or recording_urls.get("conversation_audio")
    )


def _refresh_call_recording_from_provider_sync(
    db: Session,
    call_recording: CallRecording,
    organization_id: UUID,
) -> bool:
    """Re-fetch provider call payload to refresh expiring presigned recording URLs."""
    from app.services.playground.post_call_processing import persist_provider_call_metrics

    if not call_recording.provider_call_id or not call_recording.provider_platform:
        return False

    agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()
    if not agent or not agent.voice_ai_integration_id:
        return False

    integration = db.query(Integration).filter(
        Integration.id == agent.voice_ai_integration_id,
        Integration.organization_id == organization_id,
    ).first()
    if not integration:
        return False

    try:
        provider_class = get_voice_provider(call_recording.provider_platform)
        provider = provider_class(api_key=decrypt_api_key(integration.api_key))
        if not hasattr(provider, "retrieve_call_metrics"):
            return False
        metrics = provider.retrieve_call_metrics(call_recording.provider_call_id)
        if not isinstance(metrics, dict):
            return False
        persist_provider_call_metrics(db, call_recording.id, metrics)
        db.refresh(call_recording)
        return True
    except Exception as exc:
        logger.warning(
            "[Audio Proxy] Failed to refresh provider call data for %s: %s",
            call_recording.call_short_id,
            exc,
        )
        return False


def _download_playground_recording_audio(
    call_data: Dict[str, Any],
    platform: str,
    decrypted_key: Optional[str],
    *,
    stereo: bool = False,
):
    """Download provider recording bytes using the same URL/auth rules as the audio proxy."""
    import requests as http_requests
    from app.services.voice_providers.vapi_recording import is_presigned_storage_url

    plat = (platform or "").lower()
    url = _resolve_playground_audio_url(call_data, plat, stereo=stereo)
    if not url:
        return None, None

    headers = None
    if plat == "elevenlabs" and decrypted_key:
        headers = {"xi-api-key": decrypted_key}
    elif plat == "vapi" and decrypted_key and not is_presigned_storage_url(url):
        headers = {"Authorization": f"Bearer {decrypted_key}"}

    response = http_requests.get(url, headers=headers, timeout=120)
    if response.status_code == 200:
        return response.content, response
    return None, response


def _download_playground_recording_audio_with_refresh(
    db: Session,
    call_recording: CallRecording,
    organization_id: UUID,
    call_data: Dict[str, Any],
    decrypted_key: Optional[str],
):
    """Download recording audio, refreshing provider call_data once on failure."""
    platform = (call_recording.provider_platform or "").lower()
    audio_bytes, resp = _download_playground_recording_audio(call_data, platform, decrypted_key)
    if audio_bytes:
        return audio_bytes, resp, call_data

    status_code = getattr(resp, "status_code", None)
    if status_code in (401, 403, 404) or audio_bytes is None:
        if _refresh_call_recording_from_provider_sync(db, call_recording, organization_id):
            call_data = call_recording.call_data or {}
            audio_bytes, resp = _download_playground_recording_audio(
                call_data, platform, decrypted_key
            )

    return audio_bytes, resp, call_data


def generate_unique_result_id(db: Session) -> str:
    """Generate a unique 6-digit result ID for EvaluatorResult."""
    max_attempts = 100
    for _ in range(max_attempts):
        candidate_id = f"{random.randint(100000, 999999)}"
        existing = db.query(EvaluatorResult).filter(EvaluatorResult.result_id == candidate_id).first()
        if not existing:
            return candidate_id
    raise ValueError("Failed to generate unique result ID")


def sync_provider_call_metrics(
    call_recording_id: UUID,
    provider_call_id: str,
    provider_platform: str,
    integration_api_key: str,
    max_attempts: int = 12,
    poll_interval: int = 5,
):
    """Re-fetch provider metrics and update stored call_data (no evaluator creation)."""
    import time

    from app.database import SessionLocal
    from app.services.playground.post_call_processing import (
        call_metrics_indicate_ended,
        persist_provider_call_metrics,
        provider_metrics_enriched,
    )

    db = SessionLocal()
    try:
        call_recording = db.query(CallRecording).filter(CallRecording.id == call_recording_id).first()
        if not call_recording or not provider_call_id:
            return

        try:
            provider_class = get_voice_provider(provider_platform)
            provider = provider_class(api_key=integration_api_key)
        except ValueError:
            return

        if not hasattr(provider, "retrieve_call_metrics"):
            return

        call_metrics: dict[str, Any] | None = None
        for attempt in range(max_attempts):
            if attempt > 0:
                time.sleep(poll_interval)
            try:
                call_metrics = provider.retrieve_call_metrics(provider_call_id)
                if not isinstance(call_metrics, dict):
                    continue
                persist_provider_call_metrics(db, call_recording_id, call_metrics)
                if provider_metrics_enriched(provider_platform, call_metrics):
                    break
                if call_metrics_indicate_ended(call_metrics) and attempt >= 3:
                    break
            except Exception as exc:
                logger.warning(f"[Sync Provider Metrics] attempt {attempt + 1} failed: {exc}")
    finally:
        db.close()


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
    from app.services.playground.post_call_processing import (
        call_metrics_indicate_ended,
        merge_playground_call_data,
        provider_metrics_enriched,
    )
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
                
                # Update the call recording with metrics (preserve usage-recorded flag)
                prev_data = (
                    call_recording.call_data
                    if isinstance(call_recording.call_data, dict)
                    else {}
                )
                if isinstance(call_metrics, dict):
                    call_metrics = merge_playground_call_data(prev_data, call_metrics)
                call_recording.call_data = call_metrics
                call_recording.status = CallRecordingStatus.UPDATED
                db.commit()
                db.refresh(call_recording)
                
                # Keep polling after hangup until provider enriches analysis/latency payloads.
                if call_metrics_indicate_ended(call_metrics):
                    call_complete = True
                    if provider_metrics_enriched(provider_platform, call_metrics):
                        break
                    
            except Exception as e:
                # Log error but continue polling
                logger.warning(f"[Poll Call Metrics] Error on attempt {attempt + 1}: {str(e)}")
                # If it's a 404 or similar, the call might not exist yet, continue polling
                continue
        
        # After polling is complete, create EvaluatorResult and trigger evaluation
        if call_complete and call_metrics and call_recording.agent_id:
            try:
                from app.services.playground.post_call_processing import (
                    claim_playground_evaluator_result_slot,
                    record_playground_post_call_usage_once,
                )

                should_create_evaluator, call_metrics = record_playground_post_call_usage_once(
                    db,
                    call_recording_id,
                    provider_platform=provider_platform,
                    call_metrics=call_metrics if isinstance(call_metrics, dict) else {},
                )
                if not should_create_evaluator:
                    return

                logger.info(f"[Poll Call Metrics] Call complete, creating EvaluatorResult for call {provider_call_id}")
                
                # Extract transcript and speaker segments from call_data
                transcript_text, _ = extract_transcript_from_call_data(
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
                    start_ts = call_metrics.get("start_timestamp") or call_metrics.get("startedAt")
                    end_ts = call_metrics.get("end_timestamp") or call_metrics.get("endedAt")
                    if start_ts and end_ts:
                        try:
                            from dateutil import parser
                            start_time = parser.parse(start_ts)
                            end_time = parser.parse(end_ts)
                            duration_seconds = (end_time - start_time).total_seconds()
                        except Exception:
                            pass
                
                # Download call audio from provider and upload to S3
                audio_s3_key = None
                try:
                    import requests as _http
                    import uuid as _uuid
                    from app.services.storage.s3_service import s3_service

                    recording_urls = call_metrics.get("recording_urls", {})
                    audio_bytes = None
                    plat = provider_platform.lower()

                    if plat == "elevenlabs":
                        audio_url = recording_urls.get("conversation_audio")
                        if audio_url:
                            resp = _http.get(audio_url, headers={"xi-api-key": integration_api_key}, timeout=120)
                            if resp.status_code == 200:
                                audio_bytes = resp.content
                    elif plat == "retell":
                        audio_url = call_metrics.get("recording_url")
                        if audio_url:
                            resp = _http.get(audio_url, timeout=120)
                            if resp.status_code == 200:
                                audio_bytes = resp.content
                    elif plat == "vapi":
                        artifact = call_metrics.get("artifact", {})
                        recording = artifact.get("recording", {}) if isinstance(artifact, dict) else {}
                        mono_recording = recording.get("mono", {}) if isinstance(recording, dict) else {}
                        audio_url = (
                            call_metrics.get("recordingUrl")
                            or call_metrics.get("stereoRecordingUrl")
                            or artifact.get("recordingUrl")
                            or artifact.get("stereoRecordingUrl")
                            or mono_recording.get("combinedUrl")
                            or recording_urls.get("combined_url")
                            or recording_urls.get("stereo_url")
                        )
                        if audio_url:
                            vapi_headers = {"Authorization": f"Bearer {integration_api_key}"}
                            resp = _http.get(audio_url, headers=vapi_headers, timeout=120)
                            if resp.status_code == 200:
                                audio_bytes = resp.content

                    if audio_bytes:
                        content_type = getattr(resp, "headers", {}).get("content-type", "audio/mpeg")
                        ext = "wav" if "wav" in content_type else "mp3"
                        org_id = str(call_recording.organization_id)
                        audio_s3_key = f"audio/organizations/{org_id}/agentPlayground/{provider_call_id}/{_uuid.uuid4()}.{ext}"
                        s3_service.upload_file_by_key(audio_bytes, audio_s3_key, content_type=content_type)
                        logger.info(f"[Poll Call Metrics] Uploaded call audio to S3: {audio_s3_key} ({len(audio_bytes)} bytes)")
                    else:
                        logger.warning(f"[Poll Call Metrics] Could not download audio for call {provider_call_id}")
                except Exception as audio_err:
                    logger.warning(f"[Poll Call Metrics] Audio download/upload failed: {audio_err}")

                locked_recording = claim_playground_evaluator_result_slot(
                    db,
                    call_recording_id,
                    provider_call_id=provider_call_id,
                )
                if not locked_recording:
                    return

                result_id = generate_unique_result_id(db)
                evaluator_result = EvaluatorResult(
                    result_id=result_id,
                    organization_id=locked_recording.organization_id,
                    workspace_id=locked_recording.workspace_id,
                    evaluator_id=None,
                    agent_id=locked_recording.agent_id,
                    persona_id=None,
                    scenario_id=None,
                    name=result_name,
                    duration_seconds=duration_seconds,
                    status=EvaluatorResultStatus.QUEUED.value,
                    audio_s3_key=audio_s3_key,
                    transcription=transcript_text,
                    provider_call_id=provider_call_id,
                    provider_platform=provider_platform,
                    call_data=call_metrics,
                )
                db.add(evaluator_result)
                db.flush()
                locked_recording.evaluator_result_id = evaluator_result.id
                db.commit()
                db.refresh(evaluator_result)
                
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
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Update a call recording within the active workspace, typically to set the provider_call_id.
    Triggers polling.
    """
    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id,
        CallRecording.workspace_id == workspace_id,
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
                    platform_key = (call_recording.provider_platform or "").lower()
                    # Vapi polls on call-end refresh only; update fires mid-call too.
                    if platform_key != "vapi":
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
    ui_surface: Optional[str] = None


@router.post("/web-call", response_model=Dict[str, Any])
async def create_web_call(
    web_call_data: WebCallCreate,
    background_tasks: BackgroundTasks,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Create a web call with a voice AI agent within the active workspace.
    The agent must belong to the same workspace; the resulting call recording
    is stamped with the same workspace_id.
    """
    try:
        # Get the agent (scoped to the active workspace)
        agent_uuid = UUID(web_call_data.agent_id)
        agent = db.query(Agent).filter(
            Agent.id == agent_uuid,
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
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

            platform_value = (
                integration.platform.value
                if hasattr(integration.platform, "value")
                else integration.platform
            )
            plat_lower = str(platform_value).lower()

            # Vapi Web SDK creates the call in the browser; server-side /call/web
            # would spawn a second call that never receives the user's microphone.
            if plat_lower == "vapi":
                from app.services.voice_providers.vapi import VAPI_SAMPLE_RATE

                web_call_response = {
                    "call_type": "web_call",
                    "agent_id": agent.voice_ai_agent_id,
                    "metadata": web_call_data.metadata or {},
                    "sample_rate": VAPI_SAMPLE_RATE,
                    "client_sdk_creates_call": True,
                }
                provider_call_id = None
            else:
                web_call_response = provider.create_web_call(**call_params)
                provider_call_id = web_call_response.get("call_id")

            call_short_id = generate_unique_call_short_id(db)
            stored_call_data = dict(web_call_response)
            if web_call_data.ui_surface:
                stored_call_data["ui_surface"] = web_call_data.ui_surface
            call_recording = CallRecording(
                organization_id=organization_id,
                workspace_id=workspace_id,
                call_short_id=call_short_id,
                status=CallRecordingStatus.PENDING,
                source=CallRecordingSource.PLAYGROUND,
                call_data=stored_call_data,
                provider_call_id=provider_call_id,
                provider_platform=integration.platform,
                agent_id=agent.id
            )
            db.add(call_recording)
            db.commit()
            db.refresh(call_recording)

            background_tasks.add_task(
                record_playground_web_call_started,
                organization_id,
                call_short_id,
                workspace_id=workspace_id,
                agent_id=agent.id,
            )
            
            # Start background task to poll for call metrics
            # Note: We need to pass the decrypted API key, but we should be careful with security
            # For now, we'll pass it to the background task
            # In production, you might want to store it temporarily or use a different approach
            if provider_call_id and plat_lower != "vapi":
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

            if plat_lower == "vapi" and integration.public_key:
                response["public_key"] = integration.public_key

            if plat_lower == "elevenlabs":
                response["signed_url"] = web_call_response.get("signed_url")

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
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    List playground call recordings in the active workspace.
    Includes evaluator_result_id, evaluation status, and metric_scores if evaluation has been run.
    """
    call_recordings = db.query(CallRecording).filter(
        CallRecording.organization_id == organization_id,
        CallRecording.workspace_id == workspace_id,
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
                "name": r.name,
            }
            for r in results
        }

    agent_ids = [cr.agent_id for cr in call_recordings if cr.agent_id]
    agents_by_id = {}
    if agent_ids:
        agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
        agents_by_id = {a.id: a for a in agents}

    def _display_name(cr: CallRecording) -> str:
        linked = result_info.get(str(cr.evaluator_result_id), {}) if cr.evaluator_result_id else {}
        if linked.get("name"):
            return linked["name"]
        agent = agents_by_id.get(cr.agent_id) if cr.agent_id else None
        if agent and agent.name:
            return agent.name
        return cr.call_short_id

    return [
        {
            "id": str(cr.id),
            "call_short_id": cr.call_short_id,
            "display_name": _display_name(cr),
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


@router.post("/custom-websocket-sessions", response_model=Dict[str, Any])
async def create_custom_websocket_session(
    background_tasks: BackgroundTasks,
    agent_id: str = Form(...),
    websocket_url: str = Form(...),
    transcript_entries: str = Form("[]"),
    started_at: Optional[str] = Form(None),
    ended_at: Optional[str] = Form(None),
    call_short_id: Optional[str] = Form(None),
    audio_file: Optional[UploadFile] = File(None),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Save a custom websocket test session for later evaluation (scoped to the active workspace).
    Stores transcript in call_data and uploads optional audio recording to S3.
    """
    try:
        agent_uuid = UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid agent_id")

    agent = db.query(Agent).filter(
        Agent.id == agent_uuid,
        Agent.organization_id == organization_id,
        Agent.workspace_id == workspace_id,
    ).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    try:
        parsed_entries = json.loads(transcript_entries or "[]")
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid transcript_entries payload")

    normalized_entries = []
    for entry in parsed_entries:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = (entry.get("content") or "").strip()
        if role not in {"user", "agent"} or not content:
            continue
        normalized_entries.append(
            {
                "role": role,
                "content": content,
                "timestamp": entry.get("timestamp") or ended_at or started_at,
            }
        )

    if not normalized_entries:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No transcript entries provided")

    transcript_text = "\n".join(
        [f"{'User' if item['role'] == 'user' else 'Agent'}: {item['content']}" for item in normalized_entries]
    )

    call_short_id = (call_short_id or "").strip() or generate_unique_call_short_id(db)
    audio_s3_key = None
    if audio_file:
        from app.services.storage.s3_service import s3_service

        audio_bytes = await audio_file.read()
        if audio_bytes:
            if not s3_service.is_enabled():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="S3 storage is not configured. Save without recording or enable storage.",
                )

            filename = audio_file.filename or "session.webm"
            extension = filename.split(".")[-1].lower() if "." in filename else "webm"
            content_type = audio_file.content_type or "audio/webm"
            audio_s3_key = (
                f"audio/organizations/{organization_id}/agentPlayground/customWebsocket/"
                f"{call_short_id}/{_uuid.uuid4()}.{extension}"
            )
            s3_service.upload_file_by_key(audio_bytes, audio_s3_key, content_type=content_type)

    duration_seconds = 0
    if started_at and ended_at:
        try:
            from datetime import datetime as _dt
            t_start = _dt.fromisoformat(started_at.replace("Z", "+00:00"))
            t_end = _dt.fromisoformat(ended_at.replace("Z", "+00:00"))
            duration_seconds = max(0, (t_end - t_start).total_seconds())
        except Exception:
            duration_seconds = 0

    speaker_segments = []
    for entry in normalized_entries:
        speaker = "user" if entry.get("role") == "user" else "assistant"
        speaker_segments.append({
            "speaker": speaker,
            "text": entry.get("content", ""),
            "start": 0,
            "end": 0,
        })

    call_data = {
        "source": "custom_websocket",
        "websocket_url": websocket_url,
        "messages": normalized_entries,
        "transcript": transcript_text,
        "speaker_segments": speaker_segments,
        "recording_s3_key": audio_s3_key,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration_seconds,
    }

    call_recording = CallRecording(
        organization_id=organization_id,
        workspace_id=workspace_id,
        call_short_id=call_short_id,
        status=CallRecordingStatus.UPDATED,
        source=CallRecordingSource.PLAYGROUND,
        call_data=call_data,
        provider_call_id=f"custom_{call_short_id}",
        provider_platform="custom_websocket",
        agent_id=agent.id,
    )
    db.add(call_recording)
    db.commit()
    db.refresh(call_recording)

    from app.services.synthetic_traces.trace_service import (
        close_trace_session,
        link_trace_to_call_recording,
    )

    link_trace_to_call_recording(
        db,
        organization_id=organization_id,
        call_short_id=call_short_id,
        call_recording_id=call_recording.id,
    )
    close_trace_session(
        db,
        organization_id=organization_id,
        call_short_id=call_short_id,
        workspace_id=workspace_id,
    )

    background_tasks.add_task(
        record_playground_websocket_session_started,
        organization_id,
        call_short_id,
        workspace_id=workspace_id,
    )

    return {
        "message": "Custom websocket session saved",
        "call_short_id": call_short_id,
        "audio_s3_key": audio_s3_key,
        "evaluator_result_id": None,
    }


@router.post("/custom-websocket-sessions/{call_short_id}/evaluate", response_model=Dict[str, Any])
async def evaluate_custom_websocket_session(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Queue evaluation for a saved custom websocket test session in the active workspace.
    """
    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id,
        CallRecording.workspace_id == workspace_id,
        CallRecording.source == CallRecordingSource.PLAYGROUND,
        CallRecording.provider_platform == "custom_websocket",
    ).first()

    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom websocket session not found")

    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    transcript_text = (call_data.get("transcript") or "").strip()
    if not transcript_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No transcript found for evaluation")

    existing_result = None
    if call_recording.evaluator_result_id:
        existing_result = db.query(EvaluatorResult).filter(
            EvaluatorResult.id == call_recording.evaluator_result_id,
            EvaluatorResult.organization_id == organization_id,
            EvaluatorResult.workspace_id == workspace_id,
        ).first()

    speaker_segments = call_data.get("speaker_segments") or []

    if existing_result:
        evaluator_result = existing_result
        evaluator_result.status = EvaluatorResultStatus.QUEUED.value
        evaluator_result.error_message = None
        evaluator_result.metric_scores = None
        evaluator_result.celery_task_id = None
        evaluator_result.transcription = transcript_text
        evaluator_result.speaker_segments = speaker_segments
        evaluator_result.audio_s3_key = call_data.get("recording_s3_key")
        evaluator_result.call_data = slim_call_data_for_evaluator_result(call_data)
        evaluator_result.duration_seconds = call_data.get("duration_seconds", 0)
        db.commit()
        db.refresh(evaluator_result)
    else:
        agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()
        result_id = generate_unique_result_id(db)
        result_name = f"Custom WebSocket Test - {agent.name}" if agent else "Custom WebSocket Test"

        evaluator_result = EvaluatorResult(
            result_id=result_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            evaluator_id=None,
            agent_id=call_recording.agent_id,
            persona_id=None,
            scenario_id=None,
            name=result_name,
            duration_seconds=call_data.get("duration_seconds", 0),
            status=EvaluatorResultStatus.QUEUED.value,
            audio_s3_key=call_data.get("recording_s3_key"),
            transcription=transcript_text,
            speaker_segments=speaker_segments,
            provider_call_id=call_recording.provider_call_id,
            provider_platform="custom_websocket",
            call_data=slim_call_data_for_evaluator_result(call_data),
        )
        db.add(evaluator_result)
        db.commit()
        db.refresh(evaluator_result)

        call_recording.evaluator_result_id = evaluator_result.id
        db.commit()

    try:
        from app.workers.celery_app import process_evaluator_result_task
        task = process_evaluator_result_task.delay(str(evaluator_result.id))
        evaluator_result.celery_task_id = task.id
        db.commit()
    except Exception as e:
        logger.error(f"[Custom WebSocket] Failed to trigger evaluation worker: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to trigger evaluation worker")

    return {
        "message": "Evaluation queued",
        "evaluator_result_id": str(evaluator_result.id),
        "result_id": evaluator_result.result_id,
        "task_id": task.id,
    }


@router.get("/call-recordings/{call_short_id}", response_model=Dict[str, Any])
async def get_call_recording(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Get a specific playground call recording within the active workspace.
    Returns the full JSON data stored for the call and evaluation information.
    """
    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id,
        CallRecording.workspace_id == workspace_id,
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
            eval_call_data = evaluator_result.call_data if isinstance(evaluator_result.call_data, dict) else {}
            evaluation_info = {
                "id": str(evaluator_result.id),
                "result_id": evaluator_result.result_id,
                "status": evaluator_result.status,
                "metric_scores": evaluator_result.metric_scores,
                "transcription": evaluator_result.transcription,
                "call_analysis": eval_call_data.get("call_analysis"),
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
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Re-fetch provider call metrics and wait until enriched or timeout.

    When no evaluator result exists yet, also queues post-call metric evaluation
    (same path as Retell/ElevenLabs background poll). Required for Vapi, which
    only gets a provider_call_id after the browser call ends.
    """
    import asyncio

    from app.services.playground.post_call_processing import (
        provider_metrics_enriched,
        refresh_call_metrics_sync,
    )

    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id,
        CallRecording.workspace_id == workspace_id,
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

    has_evaluator = bool(call_recording.evaluator_result_id)
    evaluation_queued = False

    if not has_evaluator:
        background_tasks.add_task(
            poll_call_metrics,
            call_recording.id,
            call_recording.provider_call_id,
            call_recording.provider_platform,
            decrypted_api_key,
        )
        evaluation_queued = True

    def _blocking_refresh() -> None:
        if has_evaluator:
            sync_provider_call_metrics(
                call_recording.id,
                call_recording.provider_call_id,
                call_recording.provider_platform,
                decrypted_api_key,
                max_attempts=12,
                poll_interval=2,
            )
        else:
            refresh_call_metrics_sync(
                call_recording.id,
                call_recording.provider_call_id,
                call_recording.provider_platform,
                decrypted_api_key,
                max_attempts=12,
                poll_interval=2,
            )

    await asyncio.to_thread(_blocking_refresh)
    db.refresh(call_recording)
    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    enriched = provider_metrics_enriched(call_recording.provider_platform or "", call_data)
    return {
        "message": "Call recording refreshed",
        "enriched": enriched,
        "evaluation_queued": evaluation_queued,
    }


@router.delete("/call-recordings/{call_short_id}", response_model=Dict[str, Any])
async def delete_call_recording(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Delete a playground call recording within the active workspace.
    """
    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id,
        CallRecording.workspace_id == workspace_id,
        CallRecording.source == CallRecordingSource.PLAYGROUND,
    ).first()
    
    if not call_recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call recording not found"
        )
    
    db.delete(call_recording)
    db.commit()
    
    return {"message": "Call recording deleted successfully"}


@router.post("/call-recordings/{call_short_id}/re-evaluate", response_model=Dict[str, Any])
async def re_evaluate_call_recording(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Re-evaluate a playground call recording within the active workspace.

    Reuses the S3 audio if it was already downloaded during the first
    evaluation. If no audio exists in S3, downloads from the provider,
    uploads, then triggers the worker for both conversation quality (LLM)
    and audio quality (acoustic / AI voice) metrics.
    """
    import uuid as _uuid
    from app.services.storage.s3_service import s3_service

    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id,
        CallRecording.workspace_id == workspace_id,
        CallRecording.source == CallRecordingSource.PLAYGROUND,
    ).first()

    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call recording not found")

    if not call_recording.provider_call_id or not call_recording.provider_platform:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Call recording has no provider data")

    call_data = call_recording.call_data or {}
    platform = (call_recording.provider_platform or "").lower()

    # --- Check if S3 audio already exists from a previous evaluation -------
    existing_result = None
    if call_recording.evaluator_result_id:
        existing_result = db.query(EvaluatorResult).filter(
            EvaluatorResult.id == call_recording.evaluator_result_id,
        ).first()

    audio_s3_key = existing_result.audio_s3_key if existing_result and existing_result.audio_s3_key else None

    # --- If no S3 audio, download from provider and upload -----------------
    if not audio_s3_key:
        agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()
        if not agent or not agent.voice_ai_integration_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent or integration not found")

        integration = db.query(Integration).filter(
            Integration.id == agent.voice_ai_integration_id,
            Integration.organization_id == organization_id,
        ).first()
        if not integration:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found")

        decrypted_key = decrypt_api_key(integration.api_key)

        audio_bytes, resp, call_data = _download_playground_recording_audio_with_refresh(
            db,
            call_recording,
            organization_id,
            call_data,
            decrypted_key,
        )

        if not audio_bytes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not download audio from provider. The recording may not be available yet.",
            )

        content_type = getattr(resp, "headers", {}).get("content-type", "audio/mpeg")
        ext = "wav" if "wav" in content_type else "mp3"
        org_id = str(organization_id)
        audio_s3_key = f"audio/organizations/{org_id}/agentPlayground/{call_recording.provider_call_id}/{_uuid.uuid4()}.{ext}"
        try:
            s3_service.upload_file_by_key(audio_bytes, audio_s3_key, content_type=content_type)
            logger.info(f"[Re-evaluate] Uploaded audio to S3: {audio_s3_key} ({len(audio_bytes)} bytes)")
        except Exception as e:
            logger.error(f"[Re-evaluate] S3 upload failed: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to store audio: {str(e)}")
    else:
        logger.info(f"[Re-evaluate] Reusing existing S3 audio: {audio_s3_key}")

    # --- Extract transcript from existing call data ------------------------
    transcript_text, _ = extract_transcript_from_call_data(call_data, platform)

    # --- Create or reset EvaluatorResult -----------------------------------
    if existing_result:
        existing_result.status = EvaluatorResultStatus.QUEUED.value
        existing_result.audio_s3_key = audio_s3_key
        # Metadata only; transcript is on existing_result.transcription.
        existing_result.call_data = (
            slim_call_data_for_evaluator_result(call_data)
            if isinstance(call_data, dict)
            else existing_result.call_data
        )
        existing_result.transcription = transcript_text or existing_result.transcription
        existing_result.metric_scores = None
        existing_result.error_message = None
        existing_result.celery_task_id = None
        db.commit()
        db.refresh(existing_result)
        evaluator_result = existing_result
        logger.info(f"[Re-evaluate] Reset existing EvaluatorResult {evaluator_result.result_id}")
    else:
        agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()
        result_id = generate_unique_result_id(db)
        duration_seconds = call_data.get("duration_seconds", 0)
        if not duration_seconds:
            start_ts = call_data.get("start_timestamp") or call_data.get("startedAt")
            end_ts = call_data.get("end_timestamp") or call_data.get("endedAt")
            if start_ts and end_ts:
                try:
                    from dateutil import parser
                    duration_seconds = (parser.parse(end_ts) - parser.parse(start_ts)).total_seconds()
                except Exception:
                    duration_seconds = 0
        result_name = f"Voice AI Call - {agent.name}" if agent else "Voice AI Call"

        evaluator_result = EvaluatorResult(
            result_id=result_id,
            organization_id=call_recording.organization_id,
            workspace_id=call_recording.workspace_id,
            evaluator_id=None,
            agent_id=call_recording.agent_id,
            persona_id=None,
            scenario_id=None,
            name=result_name,
            duration_seconds=duration_seconds,
            status=EvaluatorResultStatus.QUEUED.value,
            audio_s3_key=audio_s3_key,
            transcription=transcript_text,
            provider_call_id=call_recording.provider_call_id,
            provider_platform=platform,
            call_data=slim_call_data_for_evaluator_result(call_data),
        )
        db.add(evaluator_result)
        db.commit()
        db.refresh(evaluator_result)

        call_recording.evaluator_result_id = evaluator_result.id
        db.commit()
        logger.info(f"[Re-evaluate] Created new EvaluatorResult {evaluator_result.result_id}")

    # --- Trigger the worker ------------------------------------------------
    try:
        from app.workers.celery_app import process_evaluator_result_task
        task = process_evaluator_result_task.delay(str(evaluator_result.id))
        evaluator_result.celery_task_id = task.id
        db.commit()
        logger.info(f"[Re-evaluate] Triggered evaluation task {task.id} for result {evaluator_result.result_id}")
    except Exception as e:
        logger.error(f"[Re-evaluate] Failed to trigger Celery task: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to trigger evaluation worker")

    return {
        "message": "Re-evaluation started",
        "evaluator_result_id": str(evaluator_result.id),
        "result_id": evaluator_result.result_id,
        "audio_s3_key": audio_s3_key,
        "task_id": task.id,
    }


@router.get("/call-recordings/{call_short_id}/logs", response_model=Dict[str, Any])
async def get_call_recording_logs(
    call_short_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Return normalized provider logs for Vapi and Retell playground calls."""
    del api_key  # Dependency enforcement only
    from app.services.playground.provider_call_logs import (
        fetch_retell_call_logs,
        fetch_vapi_call_logs,
    )

    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id,
        CallRecording.workspace_id == workspace_id,
        CallRecording.source == CallRecordingSource.PLAYGROUND,
    ).first()

    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call recording not found")

    platform = (call_recording.provider_platform or "").lower()
    call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}

    if platform not in ("vapi", "retell"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider logs are only available for Vapi and Retell calls",
        )

    try:
        if platform == "retell":
            entries = fetch_retell_call_logs(call_data)
            return {"platform": platform, "entries": entries, "count": len(entries)}

        if not call_recording.provider_call_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Call recording does not have a provider call id",
            )

        agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()
        if not agent or not agent.voice_ai_integration_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent or integration not found")

        integration = db.query(Integration).filter(
            Integration.id == agent.voice_ai_integration_id,
            Integration.organization_id == organization_id,
        ).first()
        if not integration:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found")

        decrypted_api_key = decrypt_api_key(integration.api_key)
        entries = fetch_vapi_call_logs(
            api_key=decrypted_api_key,
            provider_call_id=call_recording.provider_call_id,
            call_data=call_data,
        )
        return {"platform": platform, "entries": entries, "count": len(entries)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[CallLogs] Failed to fetch logs for %s: %s", call_short_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch provider logs. Try Refresh on the call first.",
        )


@router.get("/call-recordings/{call_short_id}/audio")
async def stream_call_audio(
    call_short_id: str,
    proxy: bool = Query(False, description="Stream audio through API (CORS-safe for waveform)"),
    stereo: bool = Query(False, description="Prefer stereo recording when available"),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """
    Proxy endpoint to stream playground call recording audio in the active workspace.
    Required for providers like ElevenLabs whose audio URLs need auth headers.
    """
    import requests as http_requests

    call_recording = db.query(CallRecording).filter(
        CallRecording.call_short_id == call_short_id,
        CallRecording.organization_id == organization_id,
        CallRecording.workspace_id == workspace_id,
        CallRecording.source == CallRecordingSource.PLAYGROUND,
    ).first()

    if not call_recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call recording not found")

    call_data = call_recording.call_data or {}
    platform = (call_recording.provider_platform or "").lower()

    if platform in ("retell", "vapi", "smallest"):
        url = _resolve_playground_audio_url(call_data, platform, stereo=stereo and platform == "vapi")
        if not url:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No recording URL available")
        if proxy:
            import requests as http_requests

            upstream = http_requests.get(url, stream=True, timeout=90)
            if upstream.status_code in (401, 403) and platform == "vapi":
                upstream.close()
                if not _refresh_call_recording_from_provider_sync(db, call_recording, organization_id):
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            "Provider recording URL expired. "
                            "Use Sync provider data on the call, then try again."
                        ),
                    )
                call_data = call_recording.call_data or {}
                url = _resolve_playground_audio_url(call_data, platform, stereo=stereo)
                if not url:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="No recording URL available after refresh",
                    )
                upstream = http_requests.get(url, stream=True, timeout=90)
            if upstream.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Provider recording URL expired or unavailable. "
                        "Use Sync provider data on the call, then try again."
                    ),
                )
            content_type = upstream.headers.get("content-type", "audio/wav")
            return StreamingResponse(
                upstream.iter_content(chunk_size=8192),
                media_type=content_type,
                headers={"Content-Disposition": f'inline; filename="call_{call_short_id}.wav"'},
            )
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url)

    recording_urls = call_data.get("recording_urls", {})
    if platform == "elevenlabs":
        audio_url = recording_urls.get("conversation_audio")
        if not audio_url:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No recording URL available")

        agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()
        if not agent or not agent.voice_ai_integration_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent or integration not found")

        integration = db.query(Integration).filter(
            Integration.id == agent.voice_ai_integration_id,
            Integration.organization_id == organization_id,
        ).first()
        if not integration:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found")

        decrypted_key = decrypt_api_key(integration.api_key)

        upstream = http_requests.get(
            audio_url,
            headers={"xi-api-key": decrypted_key},
            stream=True,
            timeout=60,
        )
        if upstream.status_code != 200:
            raise HTTPException(
                status_code=upstream.status_code,
                detail=f"ElevenLabs audio fetch failed ({upstream.status_code})",
            )

        content_type = upstream.headers.get("content-type", "audio/mpeg")

        return StreamingResponse(
            upstream.iter_content(chunk_size=8192),
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="call_{call_short_id}.mp3"',
            },
        )

    # Custom WebSocket / internal test-agent sessions store audio in blob storage
    if platform in {"custom_websocket", "voice_bundle"}:
        from app.services.storage.audio_delivery import collect_call_data_audio_keys, stream_audio_from_keys

        storage_stream = stream_audio_from_keys(
            collect_call_data_audio_keys(call_data),
            filename=f"call_{call_short_id}",
            default_content_type="audio/webm" if platform == "custom_websocket" else "audio/wav",
        )
        if storage_stream:
            return storage_stream
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recording available for this session",
        )

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Audio not supported for platform: {platform}")


# ---------------------------------------------------------------------------
#  STT config resolution helper
# ---------------------------------------------------------------------------

_STT_ENV_KEYS = {
    "deepgram": "DEEPGRAM_API_KEY",
    "openai": "OPENAI_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "sarvam": "SARVAM_API_KEY",
}

_STT_DEFAULT_MODELS = {
    "deepgram": "nova-2",
    "openai": "whisper-1",
    "elevenlabs": "scribe_v2",
    "sarvam": "saaras:v3",
}


def _resolve_agent_stt_config(
    agent_id: str, organization_id: UUID, db: Session
) -> tuple:
    """Resolve STT provider, model, and API key for an agent.

    Lookup chain: Agent -> VoiceBundle -> stt_provider/stt_model
                  -> AIProvider (by org + provider name) or Integration or env var fallback.

    Returns (stt_provider, stt_model, api_key).  Any element may be None.
    """
    import os
    from sqlalchemy import func

    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.organization_id == organization_id,
    ).first()
    if not agent or not agent.voice_bundle_id:
        return None, None, None

    voice_bundle = db.query(VoiceBundle).filter(
        VoiceBundle.id == agent.voice_bundle_id,
        VoiceBundle.organization_id == organization_id,
    ).first()
    if not voice_bundle or not voice_bundle.stt_provider:
        return None, None, None

    stt_provider = (
        voice_bundle.stt_provider.value
        if hasattr(voice_bundle.stt_provider, "value")
        else str(voice_bundle.stt_provider)
    ).lower()
    stt_model = (
        getattr(voice_bundle, "stt_model", None)
        or _STT_DEFAULT_MODELS.get(stt_provider)
    )

    # 1) AIProvider
    api_key = None
    ai_prov = db.query(AIProvider).filter(
        AIProvider.organization_id == organization_id,
        AIProvider.provider == stt_provider,
        AIProvider.is_active == True,
    ).first()
    if not ai_prov:
        ai_prov = db.query(AIProvider).filter(
            AIProvider.organization_id == organization_id,
            func.lower(AIProvider.provider) == stt_provider,
            AIProvider.is_active == True,
        ).first()
    if ai_prov:
        try:
            api_key = decrypt_api_key(ai_prov.api_key)
        except Exception:
            pass

    # 2) Integration fallback
    if not api_key:
        _platform_map = {
            "deepgram": "deepgram",
            "elevenlabs": "elevenlabs",
            "sarvam": "sarvam",
        }
        plat_value = _platform_map.get(stt_provider)
        if plat_value:
            integ = db.query(Integration).filter(
                Integration.organization_id == organization_id,
                func.lower(Integration.platform) == plat_value,
                Integration.is_active == True,
            ).first()
            if integ:
                try:
                    api_key = decrypt_api_key(integ.api_key)
                except Exception:
                    pass

    # 3) Env var fallback
    if not api_key:
        env_key = _STT_ENV_KEYS.get(stt_provider)
        if env_key:
            api_key = os.getenv(env_key)

    return stt_provider, stt_model, api_key


# ---------------------------------------------------------------------------
#  GET /playground/agents/{agent_id}/stt-config
# ---------------------------------------------------------------------------

@router.get("/agents/{agent_id}/stt-config", response_model=Dict[str, Any])
async def get_agent_stt_config(
    agent_id: str,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Check whether an agent has STT configured via its voice bundle."""
    stt_provider, stt_model, stt_api_key = _resolve_agent_stt_config(
        agent_id, organization_id, db
    )
    if stt_provider and stt_api_key:
        return {"available": True, "provider": stt_provider, "model": stt_model}
    if stt_provider and not stt_api_key:
        return {
            "available": False,
            "reason": f"STT provider '{stt_provider}' is configured but no API key was found",
        }
    return {"available": False, "reason": "No voice bundle with STT configured for this agent"}


# ---------------------------------------------------------------------------
#  POST /playground/transcribe-turn
# ---------------------------------------------------------------------------

@router.post("/transcribe-turn", response_model=Dict[str, Any])
async def transcribe_turn(
    agent_id: str = Form(...),
    channel: str = Form(...),
    audio_file: UploadFile = File(...),
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Transcribe a single conversation turn (user or agent audio)."""
    import tempfile
    import os

    if channel not in ("user", "agent"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="channel must be 'user' or 'agent'",
        )

    stt_provider, stt_model, stt_api_key = _resolve_agent_stt_config(
        agent_id, organization_id, db
    )
    if not stt_provider or not stt_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="STT is not configured for this agent (missing provider or API key)",
        )

    audio_bytes = await audio_file.read()
    if not audio_bytes or len(audio_bytes) < 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file is empty or too small",
        )

    tmp_path = None
    try:
        suffix = ".wav"
        if audio_file.filename and "." in audio_file.filename:
            suffix = "." + audio_file.filename.rsplit(".", 1)[-1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        from app.services.ai.stt_clients import (
            transcribe_openai,
            transcribe_deepgram,
            transcribe_elevenlabs,
            transcribe_sarvam,
        )

        if stt_provider == "deepgram":
            result = transcribe_deepgram(tmp_path, stt_model, stt_api_key)
        elif stt_provider == "openai":
            result = transcribe_openai(tmp_path, stt_model, stt_api_key)
        elif stt_provider == "elevenlabs":
            result = transcribe_elevenlabs(tmp_path, stt_model, stt_api_key)
        elif stt_provider == "sarvam":
            result = transcribe_sarvam(tmp_path, stt_model, stt_api_key)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported STT provider: {stt_provider}",
            )

        transcript_text = (result.get("text") or "").strip()
        return {"transcript": transcript_text, "channel": channel}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[transcribe-turn] STT failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {str(e)}",
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
#  POST /playground/summarize-transcript
# ---------------------------------------------------------------------------

# Fallback defaults if the caller provides no agent context AND the voice
# bundle doesn't specify a model. The providers referenced here must exist in
# ``ModelProvider`` and be reachable via LiteLLM.
_SUMMARY_LLM_FALLBACK: List[tuple] = [
    (ModelProvider.OPENAI, "gpt-4o-mini"),
    (ModelProvider.GOOGLE, "gemini-2.5-flash"),
    (ModelProvider.ANTHROPIC, "claude-haiku-4.5"),
]


class SummarizeTranscriptRequest(BaseModel):
    transcript: Optional[str] = None
    entries: Optional[List[Dict[str, Any]]] = None
    call_short_id: Optional[str] = None
    agent_id: Optional[str] = None
    # When true, ignore any cached summary on the CallRecording and regenerate.
    force: Optional[bool] = False


def _coerce_model_provider(provider_str: str) -> Optional[ModelProvider]:
    """Safely convert a string like ``"openai"`` to the matching enum."""
    if not provider_str:
        return None
    want = provider_str.strip().lower()
    for m in ModelProvider:
        if m.value.lower() == want:
            return m
    return None


def _resolve_agent_llm_config(
    agent_id: Optional[UUID], organization_id: UUID, db: Session
) -> tuple:
    """Resolve the LLM provider + model for an agent via its VoiceBundle.

    Returns ``(ModelProvider | None, model_name | None)``.
    """
    if not agent_id:
        return None, None

    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.organization_id == organization_id,
    ).first()
    if not agent or not agent.voice_bundle_id:
        return None, None

    voice_bundle = db.query(VoiceBundle).filter(
        VoiceBundle.id == agent.voice_bundle_id,
        VoiceBundle.organization_id == organization_id,
    ).first()
    if not voice_bundle or not voice_bundle.llm_provider:
        return None, None

    provider_enum = _coerce_model_provider(voice_bundle.llm_provider)
    if not provider_enum:
        return None, None

    return provider_enum, (voice_bundle.llm_model or None)


def _pick_fallback_llm(organization_id: UUID, db: Session) -> Optional[tuple]:
    """Pick any (ModelProvider, default_model) that has an active AIProvider
    row for the organization. Used only when the agent / voice bundle doesn't
    specify an LLM.
    """
    from sqlalchemy import func

    for provider_enum, default_model in _SUMMARY_LLM_FALLBACK:
        provider_value = provider_enum.value
        ai_prov = db.query(AIProvider).filter(
            AIProvider.organization_id == organization_id,
            func.lower(AIProvider.provider) == provider_value.lower(),
            AIProvider.is_active == True,
        ).first()
        if ai_prov:
            return provider_enum, default_model
    return None


def _format_entries_as_transcript(entries: List[Dict[str, Any]]) -> str:
    """Turn a list of {role, content} entries into a plain-text transcript."""
    lines = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        role = (e.get("role") or "").strip().lower()
        text = (e.get("content") or e.get("text") or "").strip()
        if not text:
            continue
        label = "User" if role in ("user", "caller", "speaker 1") else "Agent"
        lines.append(f"{label}: {text}")
    return "\n".join(lines)


@router.post("/summarize-transcript", response_model=Dict[str, Any])
async def summarize_transcript(
    payload: SummarizeTranscriptRequest = Body(...),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Generate a short natural-language summary of a transcript using an LLM.

    Provider selection order:
      1. The voice bundle of ``agent_id`` (or the agent on ``call_short_id``).
      2. Any configured AIProvider matching the fallback preference list.
    """
    from contextlib import nullcontext

    from app.services.ai.llm_service import llm_service
    from app.services.usage.context import llm_usage_context, usage_context_for_agent

    transcript_text = (payload.transcript or "").strip()
    if not transcript_text and payload.entries:
        transcript_text = _format_entries_as_transcript(payload.entries)

    if not transcript_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either `transcript` text or non-empty `entries`.",
        )

    # Defensive cap on transcript size to protect token budgets. Keep the tail
    # so the most recent exchange wins.
    MAX_CHARS = 16000
    if len(transcript_text) > MAX_CHARS:
        transcript_text = transcript_text[-MAX_CHARS:]

    # --- Resolve CallRecording (for caching) and agent context -------------
    call_rec: Optional[CallRecording] = None
    if payload.call_short_id:
        call_rec = db.query(CallRecording).filter(
            CallRecording.call_short_id == payload.call_short_id,
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
        ).first()

    # Cache hit: serve the previously generated summary without re-calling the LLM.
    if call_rec and not payload.force and isinstance(call_rec.call_data, dict):
        cached = call_rec.call_data.get("ai_summary")
        if isinstance(cached, dict) and (cached.get("text") or "").strip():
            return {
                "summary": cached.get("text", ""),
                "provider": cached.get("provider", ""),
                "model": cached.get("model", ""),
                "source": cached.get("source", "voice_bundle"),
                "cached": True,
                "generated_at": cached.get("generated_at"),
                "usage": {},
            }

    agent_uuid: Optional[UUID] = None
    if payload.agent_id:
        try:
            agent_uuid = UUID(payload.agent_id)
        except ValueError:
            agent_uuid = None

    if not agent_uuid and call_rec and call_rec.agent_id:
        agent_uuid = call_rec.agent_id

    # --- Pick LLM: prefer voice-bundle config, else fall back --------------
    llm_provider, llm_model = _resolve_agent_llm_config(
        agent_uuid, organization_id, db
    )
    source = "voice_bundle"

    if not llm_provider:
        picked = _pick_fallback_llm(organization_id, db)
        if not picked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No LLM is configured. Either set an LLM on the agent's voice bundle, "
                    "or add an active AIProvider (OpenAI / Google / Anthropic) for this organization."
                ),
            )
        llm_provider, llm_model = picked
        source = "org_fallback"

    if not llm_model:
        # Voice bundle had a provider but no model; fill in a safe default.
        defaults = {
            ModelProvider.OPENAI: "gpt-4o-mini",
            ModelProvider.GOOGLE: "gemini-2.5-flash",
            ModelProvider.ANTHROPIC: "claude-haiku-4.5",
        }
        llm_model = defaults.get(llm_provider) or "gpt-4o-mini"

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert call analyst. Read the conversation transcript "
                "the user provides and write a concise, neutral summary of what happened. "
                "Focus on the caller's intent, what the agent did, any outcomes or "
                "action items, and the overall tone. Respond in 2-4 plain-text "
                "sentences only — no bullet points, no markdown, no preamble."
            ),
        },
        {
            "role": "user",
            "content": f"Conversation transcript:\n\n{transcript_text}",
        },
    ]

    try:
        usage_ctx = nullcontext()
        if agent_uuid:
            agent_row = db.query(Agent).filter(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id,
            ).first()
            if agent_row:
                usage_ctx = llm_usage_context(
                    usage_context_for_agent(agent_row, workspace_id=workspace_id)
                )

        with usage_ctx:
            result = llm_service.generate_response(
                messages=messages,
                llm_provider=llm_provider,
                llm_model=llm_model,
                organization_id=organization_id,
                db=db,
                temperature=0.3,
                max_tokens=400,
            )
    except Exception as e:
        logger.error(f"[summarize-transcript] LLM call failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Summary generation failed: {str(e)}",
        )

    summary = (result.get("text") or "").strip()
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LLM returned an empty summary.",
        )

    generated_at = datetime.utcnow().isoformat() + "Z"

    # Persist on the CallRecording so subsequent loads don't re-invoke the LLM.
    if call_rec is not None:
        try:
            # Reassign the dict so SQLAlchemy notices the JSON column changed.
            existing = call_rec.call_data if isinstance(call_rec.call_data, dict) else {}
            new_call_data = dict(existing)
            new_call_data["ai_summary"] = {
                "text": summary,
                "provider": llm_provider.value,
                "model": llm_model,
                "source": source,
                "generated_at": generated_at,
            }
            call_rec.call_data = new_call_data
            db.commit()
        except Exception as e:
            # Non-fatal: return the generated summary even if persistence fails.
            logger.warning(f"[summarize-transcript] Failed to cache summary: {e}")
            db.rollback()

    return {
        "summary": summary,
        "provider": llm_provider.value,
        "model": llm_model,
        "source": source,
        "cached": False,
        "generated_at": generated_at,
        "usage": result.get("usage", {}),
    }


from app.core.auth.capabilities import SIM_MANAGE, SIM_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=SIM_VIEW,
    manage_capability=SIM_MANAGE,
)

