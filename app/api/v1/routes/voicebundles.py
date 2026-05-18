"""
VoiceBundle API Routes
Complete CRUD operations for VoiceBundles (STT + LLM + TTS configurations).

Each leg (stt/llm/tts/s2s) optionally pins a specific credential row in
``aiproviders`` or ``integrations`` so that organizations with multiple
keys per provider can deterministically choose which key the bundle
uses. When the ``*_credential_id`` is omitted the runtime resolver
falls back to the row marked ``is_default`` for the leg's provider.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional
from typing import List
from uuid import UUID

from app.dependencies import get_db, get_organization_id
from app.models.database import (
    AIProvider,
    Agent,
    Integration,
    ModelProvider,
    TestAgentConversation,
    VoiceBundle,
)
from app.models.schemas import (
    VoiceBundleCreate, VoiceBundleUpdate, VoiceBundleResponse
)

router = APIRouter(prefix="/voicebundles", tags=["voicebundles"])


def _to_str(value) -> Optional[str]:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _validate_credential(
    db: Session,
    organization_id: UUID,
    provider: Optional[ModelProvider],
    credential_id: Optional[UUID],
    leg: str,
) -> None:
    """Ensure a credential id (if given) belongs to the org and matches the provider.

    Looks up the id in both ``aiproviders`` and ``integrations``; the
    target table varies by provider (e.g. OpenAI -> aiproviders,
    ElevenLabs -> integrations).
    """
    if credential_id is None:
        return
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{leg}_credential_id requires {leg}_provider to be set",
        )

    provider_str = _to_str(provider) or ""

    ai_row = (
        db.query(AIProvider)
        .filter(
            AIProvider.id == credential_id,
            AIProvider.organization_id == organization_id,
        )
        .first()
    )
    if ai_row:
        if (ai_row.provider or "").lower() != provider_str.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{leg}_credential_id points to an AIProvider for "
                    f"{ai_row.provider}, which does not match {leg}_provider={provider_str}"
                ),
            )
        return

    integ_row = (
        db.query(Integration)
        .filter(
            Integration.id == credential_id,
            Integration.organization_id == organization_id,
        )
        .first()
    )
    if integ_row:
        platform = integ_row.platform.value if hasattr(integ_row.platform, "value") else str(integ_row.platform)
        if (platform or "").lower() != provider_str.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{leg}_credential_id points to an Integration for "
                    f"{platform}, which does not match {leg}_provider={provider_str}"
                ),
            )
        return

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{leg}_credential_id does not match any credential in this organization",
    )


@router.post("", response_model=VoiceBundleResponse, status_code=status.HTTP_201_CREATED, operation_id="createVoiceBundle")
async def create_voicebundle(
    voicebundle: VoiceBundleCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db)
):
    """Create a new VoiceBundle"""
    bundle_type_value = voicebundle.bundle_type.value if hasattr(voicebundle.bundle_type, 'value') else str(voicebundle.bundle_type)

    _validate_credential(db, organization_id, voicebundle.stt_provider, voicebundle.stt_credential_id, "stt")
    _validate_credential(db, organization_id, voicebundle.llm_provider, voicebundle.llm_credential_id, "llm")
    _validate_credential(db, organization_id, voicebundle.tts_provider, voicebundle.tts_credential_id, "tts")
    _validate_credential(db, organization_id, voicebundle.s2s_provider, voicebundle.s2s_credential_id, "s2s")

    db_voicebundle = VoiceBundle(
        organization_id=organization_id,
        name=voicebundle.name,
        description=voicebundle.description,
        bundle_type=bundle_type_value,
        stt_provider=voicebundle.stt_provider,
        stt_credential_id=voicebundle.stt_credential_id,
        stt_model=voicebundle.stt_model,
        llm_provider=voicebundle.llm_provider,
        llm_credential_id=voicebundle.llm_credential_id,
        llm_model=voicebundle.llm_model,
        llm_temperature=voicebundle.llm_temperature,
        llm_max_tokens=voicebundle.llm_max_tokens,
        llm_config=voicebundle.llm_config,
        tts_provider=voicebundle.tts_provider,
        tts_credential_id=voicebundle.tts_credential_id,
        tts_model=voicebundle.tts_model,
        tts_voice=voicebundle.tts_voice,
        tts_config=voicebundle.tts_config,
        s2s_provider=voicebundle.s2s_provider,
        s2s_credential_id=voicebundle.s2s_credential_id,
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

    update_data = voicebundle_update.model_dump(exclude_unset=True)

    # Validate any credential ids (or clears) against the bundle's effective
    # provider after the update is applied.
    leg_pairs = (
        ("stt", "stt_provider", "stt_credential_id"),
        ("llm", "llm_provider", "llm_credential_id"),
        ("tts", "tts_provider", "tts_credential_id"),
        ("s2s", "s2s_provider", "s2s_credential_id"),
    )
    for leg, provider_field, credential_field in leg_pairs:
        if credential_field in update_data:
            new_credential_id = update_data[credential_field]
            new_provider = update_data.get(provider_field, getattr(db_voicebundle, provider_field))
            _validate_credential(db, organization_id, new_provider, new_credential_id, leg)

    for field, value in update_data.items():
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

