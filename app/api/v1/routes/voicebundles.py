"""
VoiceBundle API Routes
Complete CRUD operations for VoiceBundles (STT + LLM + TTS configurations)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.dependencies import get_db, get_organization_id
from app.models.database import VoiceBundle
from app.models.schemas import (
    VoiceBundleCreate, VoiceBundleUpdate, VoiceBundleResponse
)

router = APIRouter(prefix="/voicebundles", tags=["voicebundles"])


@router.post("", response_model=VoiceBundleResponse, status_code=status.HTTP_201_CREATED)
async def create_voicebundle(
    voicebundle: VoiceBundleCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create a new VoiceBundle"""
    db_voicebundle = VoiceBundle(
        organization_id=organization_id,
        name=voicebundle.name,
        description=voicebundle.description,
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
        extra_metadata=voicebundle.extra_metadata,
    )
    db.add(db_voicebundle)
    db.commit()
    db.refresh(db_voicebundle)
    
    return db_voicebundle


@router.get("", response_model=List[VoiceBundleResponse])
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


@router.put("/{voicebundle_id}", response_model=VoiceBundleResponse)
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
        setattr(db_voicebundle, field, value)
    
    db.commit()
    db.refresh(db_voicebundle)
    
    return db_voicebundle


@router.delete("/{voicebundle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voicebundle(
    voicebundle_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Delete a VoiceBundle"""
    db_voicebundle = db.query(VoiceBundle).filter(
        VoiceBundle.id == voicebundle_id,
        VoiceBundle.organization_id == organization_id
    ).first()
    
    if not db_voicebundle:
        raise HTTPException(
            status_code=404, detail=f"VoiceBundle {voicebundle_id} not found"
        )
    
    db.delete(db_voicebundle)
    db.commit()
    
    return None

