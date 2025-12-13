"""
Playground API Routes
API endpoints for testing voice agents in the playground
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, List
from uuid import UUID
from pydantic import BaseModel
import random

from app.dependencies import get_db, get_organization_id, get_api_key
from app.models.database import Agent, Integration, IntegrationPlatform, CallRecording, CallRecordingStatus
from app.core.encryption import decrypt_api_key
from app.services.voice_providers import get_voice_provider

router = APIRouter(prefix="/playground", tags=["playground"])


def generate_unique_call_short_id(db: Session) -> str:
    """Generate a unique 6-digit call short ID."""
    max_attempts = 100
    for _ in range(max_attempts):
        call_short_id = f"{random.randint(100000, 999999)}"
        existing = db.query(CallRecording).filter(CallRecording.call_short_id == call_short_id).first()
        if not existing:
            return call_short_id
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to generate unique call short ID"
    )


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
    try:
        call_recording = db.query(CallRecording).filter(CallRecording.id == call_recording_id).first()
        if not call_recording:
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
                if provider_platform == "retell" and hasattr(provider, "retrieve_call_metrics"):
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
                if end_timestamp or call_status in ["ended", "completed", "failed"]:
                    break
                    
            except Exception as e:
                # Log error but continue polling
                print(f"[Poll Call Metrics] Error on attempt {attempt + 1}: {str(e)}")
                # If it's a 404 or similar, the call might not exist yet, continue polling
                continue
        
    finally:
        db.close()


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
        if agent.call_medium.value != "web_call":
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
            provider_class = get_voice_provider(integration.platform.value)
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
            
            print(f"[Playground] Creating web call - Agent ID: {agent.id}, Retell Agent ID: {agent.voice_ai_agent_id}, Platform: {integration.platform.value}")
            
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
            if integration.platform.value != "retell" and web_call_data.custom_sip_headers:
                call_params["custom_sip_headers"] = web_call_data.custom_sip_headers
            
            web_call_response = provider.create_web_call(**call_params)
            
            # Store call recording in database
            call_short_id = generate_unique_call_short_id(db)
            provider_call_id = web_call_response.get("call_id")
            
            call_recording = CallRecording(
                organization_id=organization_id,
                call_short_id=call_short_id,
                status=CallRecordingStatus.PENDING,
                call_data=web_call_response,  # Store initial response
                provider_call_id=provider_call_id,
                provider_platform=integration.platform.value,
                agent_id=agent.id
            )
            db.add(call_recording)
            db.commit()
            db.refresh(call_recording)
            
            # Start background task to poll for call metrics
            # Note: We need to pass the decrypted API key, but we should be careful with security
            # For now, we'll pass it to the background task
            # In production, you might want to store it temporarily or use a different approach
            background_tasks.add_task(
                poll_call_metrics,
                call_recording.id,
                provider_call_id,
                integration.platform.value,
                decrypted_api_key
            )
            
            # Add call_short_id to response for frontend
            response = web_call_response.copy()
            response["call_short_id"] = call_short_id
            
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
    """
    call_recordings = db.query(CallRecording).filter(
        CallRecording.organization_id == organization_id
    ).order_by(CallRecording.created_at.desc()).offset(skip).limit(limit).all()
    
    return [
        {
            "id": str(cr.id),
            "call_short_id": cr.call_short_id,
            "status": cr.status.value if cr.status else None,
            "provider_platform": cr.provider_platform,
            "provider_call_id": cr.provider_call_id,
            "agent_id": str(cr.agent_id) if cr.agent_id else None,
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
    Returns the full JSON data stored for the call.
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
    
    return {
        "id": str(call_recording.id),
        "call_short_id": call_recording.call_short_id,
        "status": call_recording.status.value if call_recording.status else None,
        "provider_platform": call_recording.provider_platform,
        "provider_call_id": call_recording.provider_call_id,
        "agent_id": str(call_recording.agent_id) if call_recording.agent_id else None,
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
        CallRecording.organization_id == organization_id
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

