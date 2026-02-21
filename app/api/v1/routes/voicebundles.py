"""
VoiceBundle API Routes
Complete CRUD operations for VoiceBundles (STT + LLM + TTS configurations)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.dependencies import get_db, get_organization_id
from app.models.database import VoiceBundle, Agent, TestAgentConversation
from app.models.schemas import (
    VoiceBundleCreate, VoiceBundleUpdate, VoiceBundleResponse
)

router = APIRouter(prefix="/voicebundles", tags=["voicebundles"])


@router.post("", response_model=VoiceBundleResponse, status_code=status.HTTP_201_CREATED, operation_id="createVoiceBundle")
async def create_voicebundle(
    voicebundle: VoiceBundleCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create a new VoiceBundle"""
    # Convert enum to string value for database storage
    bundle_type_value = voicebundle.bundle_type.value if hasattr(voicebundle.bundle_type, 'value') else str(voicebundle.bundle_type)
    
    db_voicebundle = VoiceBundle(
        organization_id=organization_id,
        name=voicebundle.name,
        description=voicebundle.description,
        bundle_type=bundle_type_value,
        stt_provider=voicebundle.stt_provider,
        stt_model=voicebundle.stt_model,
        llm_provider=voicebundle.llm_provider,
        llm_model=voicebundle.llm_model,
        llm_temperature=voicebundle.llm_temperature,
        llm_max_tokens=voicebundle.llm_max_tokens,
        llm_config=voicebundle.llm_config,
        tts_provider=voicebundle.tts_provider,
        tts_model=voicebundle.tts_model,
        tts_voice=voicebundle.tts_voice,
        tts_config=voicebundle.tts_config,
        s2s_provider=voicebundle.s2s_provider,
        s2s_model=voicebundle.s2s_model,
        s2s_config=voicebundle.s2s_config,
        extra_metadata=voicebundle.extra_metadata,
    )
    db.add(db_voicebundle)
    db.commit()
    db.refresh(db_voicebundle)
    
    return db_voicebundle


@router.get("", response_model=List[VoiceBundleResponse], operation_id="listVoiceBundles")
async def list_voicebundles(
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """List all VoiceBundles for the organization"""
    voicebundles = db.query(VoiceBundle).filter(
        VoiceBundle.organization_id == organization_id
    ).offset(skip).limit(limit).all()
    
    return voicebundles


@router.get("/{voicebundle_id}", response_model=VoiceBundleResponse)
async def get_voicebundle(
    voicebundle_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Get a specific VoiceBundle"""
    voicebundle = db.query(VoiceBundle).filter(
        VoiceBundle.id == voicebundle_id,
        VoiceBundle.organization_id == organization_id
    ).first()
    
    if not voicebundle:
        raise HTTPException(
            status_code=404, detail=f"VoiceBundle {voicebundle_id} not found"
        )
    
    return voicebundle


@router.put("/{voicebundle_id}", response_model=VoiceBundleResponse, operation_id="updateVoiceBundle")
async def update_voicebundle(
    voicebundle_id: UUID,
    voicebundle_update: VoiceBundleUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Update an existing VoiceBundle"""
    db_voicebundle = db.query(VoiceBundle).filter(
        VoiceBundle.id == voicebundle_id,
        VoiceBundle.organization_id == organization_id
    ).first()
    
    if not db_voicebundle:
        raise HTTPException(
            status_code=404, detail=f"VoiceBundle {voicebundle_id} not found"
        )
    
    update_data = voicebundle_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        # Convert bundle_type enum to string value if present
        if field == 'bundle_type' and value is not None:
            value = value.value if hasattr(value, 'value') else str(value)
        setattr(db_voicebundle, field, value)
    
    db.commit()
    db.refresh(db_voicebundle)
    
    return db_voicebundle


@router.delete("/{voicebundle_id}", operation_id="deleteVoiceBundle")
async def delete_voicebundle(
    voicebundle_id: UUID,
    force: bool = Query(False, description="Force delete with all dependent records"),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Delete a VoiceBundle. Returns 409 if dependent records exist unless force=true."""
    db_voicebundle = db.query(VoiceBundle).filter(
        VoiceBundle.id == voicebundle_id,
        VoiceBundle.organization_id == organization_id
    ).first()

    if not db_voicebundle:
        raise HTTPException(
            status_code=404, detail=f"VoiceBundle {voicebundle_id} not found"
        )

    agents_count = db.query(Agent).filter(
        Agent.voice_bundle_id == voicebundle_id,
        Agent.organization_id == organization_id,
    ).count()

    test_conversations_count = db.query(TestAgentConversation).filter(
        TestAgentConversation.voice_bundle_id == voicebundle_id,
        TestAgentConversation.organization_id == organization_id,
    ).count()

    dependencies = {}
    if agents_count > 0:
        dependencies["agents"] = agents_count
    if test_conversations_count > 0:
        dependencies["test_conversations"] = test_conversations_count

    if dependencies and not force:
        parts = []
        if agents_count > 0:
            parts.append(f"{agents_count} agent(s)")
        if test_conversations_count > 0:
            parts.append(f"{test_conversations_count} test conversation(s)")

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"Cannot delete VoiceBundle. It is referenced by: {', '.join(parts)}.",
                "dependencies": dependencies,
                "hint": "Use force=true to delete this VoiceBundle and unlink/remove dependent records.",
            },
        )

    if dependencies:
        db.query(Agent).filter(
            Agent.voice_bundle_id == voicebundle_id,
            Agent.organization_id == organization_id,
        ).update({Agent.voice_bundle_id: None}, synchronize_session=False)

        db.query(TestAgentConversation).filter(
            TestAgentConversation.voice_bundle_id == voicebundle_id,
            TestAgentConversation.organization_id == organization_id,
        ).update({TestAgentConversation.voice_bundle_id: None}, synchronize_session=False)

    db.delete(db_voicebundle)
    db.commit()

    if dependencies:
        return JSONResponse(
            status_code=200,
            content={
                "message": "VoiceBundle deleted and dependent records unlinked successfully.",
                "unlinked": dependencies,
            },
        )

    return JSONResponse(status_code=204, content=None)

