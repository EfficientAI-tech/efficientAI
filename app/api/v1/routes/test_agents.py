"""
Test Agents API Routes
API endpoints for managing test agent conversations.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Optional

from app.database import get_db
from app.dependencies import get_organization_id, get_api_key
from app.models.database import TestAgentConversation
from app.models.schemas import (
    TestAgentConversationCreate,
    TestAgentConversationUpdate,
    TestAgentConversationResponse
)
from app.services.test_agent_service import test_agent_service

router = APIRouter(prefix="/test-agents", tags=["test-agents"])


@router.post("/conversations", response_model=TestAgentConversationResponse, status_code=status.HTTP_201_CREATED, operation_id="createTestAgentConversation")
async def create_conversation(
    conversation: TestAgentConversationCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create a new test agent conversation."""
    try:
        db_conversation = test_agent_service.create_conversation(
            agent_id=conversation.agent_id,
            persona_id=conversation.persona_id,
            scenario_id=conversation.scenario_id,
            voice_bundle_id=conversation.voice_bundle_id,
            organization_id=organization_id,
            db=db,
            conversation_metadata=conversation.conversation_metadata
        )
        return db_conversation
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create conversation: {str(e)}")


@router.get("/conversations", response_model=List[TestAgentConversationResponse])
async def list_conversations(
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """List all test agent conversations for the organization."""
    conversations = db.query(TestAgentConversation).filter(
        TestAgentConversation.organization_id == organization_id
    ).offset(skip).limit(limit).all()
    return conversations


@router.get("/conversations/{conversation_id}", response_model=TestAgentConversationResponse, operation_id="getTestAgentConversation")
async def get_conversation(
    conversation_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get a specific test agent conversation."""
    conversation = db.query(TestAgentConversation).filter(
        TestAgentConversation.id == conversation_id,
        TestAgentConversation.organization_id == organization_id
    ).first()
    if not conversation:
        raise HTTPException(
            status_code=404, detail=f"Conversation {conversation_id} not found"
        )
    return conversation


@router.post("/conversations/{conversation_id}/start", response_model=TestAgentConversationResponse, operation_id="startTestAgentConversation")
async def start_conversation(
    conversation_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Start a test agent conversation."""
    try:
        conversation = test_agent_service.start_conversation(
            conversation_id=conversation_id,
            organization_id=organization_id,
            db=db
        )
        return conversation
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start conversation: {str(e)}")


@router.post("/conversations/{conversation_id}/process-audio", operation_id="processTestAgentAudio")
async def process_audio_chunk(
    conversation_id: UUID,
    audio_file: UploadFile = File(...),
    chunk_timestamp: Optional[float] = None,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """
    Process an audio chunk from the voice AI agent.
    
    This endpoint:
    1. Receives audio chunk from voice AI agent
    2. Transcribes it using STT
    3. Generates response using LLM
    4. Converts response to speech using TTS
    5. Returns response audio and transcription
    """
    try:
        # Read audio file
        audio_bytes = await audio_file.read()
        
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file")
        
        # Process audio chunk
        result = test_agent_service.process_audio_chunk(
            conversation_id=conversation_id,
            audio_chunk=audio_bytes,
            organization_id=organization_id,
            db=db,
            chunk_timestamp=chunk_timestamp
        )
        
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Return response audio as file and transcription
        from fastapi.responses import Response
        
        return {
            "transcription": result.get("transcription"),
            "metadata": result.get("metadata"),
            "audio_url": f"/test-agents/conversations/{conversation_id}/response-audio"
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process audio: {str(e)}\nDetails: {error_details}"
        )


@router.get("/conversations/{conversation_id}/response-audio", operation_id="getTestAgentResponseAudio")
async def get_response_audio(
    conversation_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get the latest response audio for a conversation."""
    conversation = db.query(TestAgentConversation).filter(
        TestAgentConversation.id == conversation_id,
        TestAgentConversation.organization_id == organization_id
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Get latest test agent audio segment
    if not conversation.live_transcription:
        raise HTTPException(status_code=404, detail="No audio available")
    
    # Find latest test agent turn
    test_agent_turns = [
        turn for turn in conversation.live_transcription
        if turn.get("speaker") == "test_agent"
    ]
    
    if not test_agent_turns:
        raise HTTPException(status_code=404, detail="No response audio available")
    
    latest_turn = test_agent_turns[-1]
    audio_key = latest_turn.get("audio_segment_key")
    
    if not audio_key:
        raise HTTPException(status_code=404, detail="Audio segment key not found")
    
    # Download from S3
    from app.services.s3_service import s3_service
    try:
        audio_bytes = s3_service.download_file_by_key(audio_key)
        from fastapi.responses import Response
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve audio: {str(e)}")


@router.post("/conversations/{conversation_id}/end", response_model=TestAgentConversationResponse, operation_id="endTestAgentConversation")
async def end_conversation(
    conversation_id: UUID,
    final_audio_key: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """End a test agent conversation."""
    try:
        conversation = test_agent_service.end_conversation(
            conversation_id=conversation_id,
            organization_id=organization_id,
            db=db,
            final_audio_key=final_audio_key
        )
        return conversation
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to end conversation: {str(e)}")


@router.put("/conversations/{conversation_id}", response_model=TestAgentConversationResponse)
async def update_conversation(
    conversation_id: UUID,
    conversation_update: TestAgentConversationUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Update a test agent conversation."""
    conversation = db.query(TestAgentConversation).filter(
        TestAgentConversation.id == conversation_id,
        TestAgentConversation.organization_id == organization_id
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    update_data = conversation_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(conversation, field, value)
    
    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Delete a test agent conversation."""
    conversation = db.query(TestAgentConversation).filter(
        TestAgentConversation.id == conversation_id,
        TestAgentConversation.organization_id == organization_id
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    db.delete(conversation)
    db.commit()
    return None

