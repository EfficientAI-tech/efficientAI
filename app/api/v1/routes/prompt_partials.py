"""
Prompt Partials API Routes
CRUD operations with version history for reusable prompt templates.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from loguru import logger

from app.dependencies import get_db, get_organization_id, get_api_key
from app.models.database import PromptPartial, PromptPartialVersion
from app.models.schemas import (
    PromptPartialCreate,
    PromptPartialUpdate,
    PromptPartialResponse,
    PromptPartialDetailResponse,
    PromptPartialVersionResponse,
)

router = APIRouter(prefix="/prompt-partials", tags=["prompt-partials"])


# ======================================================================
# AI Generation schemas and prompts
# ======================================================================

class GeneratePromptRequest(BaseModel):
    description: str
    tone: Optional[str] = "professional"
    format_style: Optional[str] = "structured"
    provider: Optional[str] = None
    model: Optional[str] = None


class ImprovePromptRequest(BaseModel):
    content: str
    instructions: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None


GENERATE_PROMPT_SYSTEM = (
    "You are an expert prompt engineer. Your job is to create high-quality, well-structured prompts "
    "for AI/LLM systems. The user will describe what they need and you will generate a complete, "
    "production-ready prompt in markdown format.\n\n"
    "Guidelines:\n"
    "- Use clear markdown structure: headings, bullet points, numbered lists\n"
    "- Include role/persona definition, context, constraints, and output format sections as appropriate\n"
    "- Be specific and actionable — avoid vague instructions\n"
    "- Include example inputs/outputs where helpful\n"
    "- Return ONLY the prompt content in markdown, no preamble or explanation about what you did"
)

IMPROVE_PROMPT_SYSTEM = (
    "You are an expert prompt engineer and technical writer. Your job is to take an existing prompt "
    "and improve it: better structure, clearer instructions, fix ambiguities, and format as clean markdown.\n\n"
    "Guidelines:\n"
    "- Preserve ALL original meaning and intent — do not add, remove, or fabricate information\n"
    "- Organize into clear sections with markdown headings, bullets, and lists\n"
    "- Improve clarity, specificity, and actionability\n"
    "- Fix grammar and formatting issues\n"
    "- Return ONLY the improved prompt in markdown, no preamble or explanation"
)


def _get_llm_provider_and_model(
    organization_id: UUID,
    db: Session,
    provider: Optional[str] = None,
    model: Optional[str] = None,
):
    """Resolve the LLM provider and model to use, falling back to org defaults."""
    from app.models.database import AIProvider
    from app.models.enums import ModelProvider

    if provider and model:
        try:
            provider_enum = ModelProvider(provider.lower())
        except ValueError:
            raise HTTPException(400, f"Unsupported LLM provider: {provider}")
        return provider_enum, model

    for prov in [ModelProvider.OPENAI, ModelProvider.ANTHROPIC, ModelProvider.GOOGLE]:
        ai_prov = db.query(AIProvider).filter(
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True,
            AIProvider.provider == prov.value,
        ).first()
        if ai_prov:
            default_models = {
                ModelProvider.OPENAI: "gpt-4o-mini",
                ModelProvider.ANTHROPIC: "claude-sonnet-4-20250514",
                ModelProvider.GOOGLE: "gemini-2.0-flash",
            }
            return prov, model or default_models.get(prov, "gpt-4o-mini")

    raise HTTPException(
        400,
        "No active AI provider configured. Add an OpenAI, Anthropic, or Google provider in AI Providers settings.",
    )


@router.post("/generate")
async def generate_prompt_with_ai(
    data: GeneratePromptRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Generate a new prompt using AI from a description."""
    from app.services.llm_service import llm_service

    if not data.description.strip():
        raise HTTPException(400, "Description is required")

    provider_enum, model_str = _get_llm_provider_and_model(
        organization_id, db, data.provider, data.model
    )

    user_prompt = (
        f"Create a prompt for the following use case:\n\n"
        f"Description: {data.description}\n"
        f"Tone: {data.tone or 'professional'}\n"
        f"Format: {data.format_style or 'structured'}\n\n"
        f"Generate a complete, production-ready prompt in markdown format."
    )

    messages = [
        {"role": "system", "content": GENERATE_PROMPT_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = llm_service.generate_response(
            messages=messages,
            llm_provider=provider_enum,
            llm_model=model_str,
            organization_id=organization_id,
            db=db,
            temperature=0.7,
            max_tokens=4000,
        )
        return {"content": result["text"], "provider": provider_enum.value, "model": model_str}
    except Exception as e:
        logger.error(f"[PromptPartials] AI generation failed: {repr(e)}")
        raise HTTPException(500, f"AI generation failed: {str(e)}")


@router.post("/improve")
async def improve_prompt_with_ai(
    data: ImprovePromptRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Improve/reformat existing prompt content using AI."""
    from app.services.llm_service import llm_service

    if not data.content.strip():
        raise HTTPException(400, "Content is required")

    provider_enum, model_str = _get_llm_provider_and_model(
        organization_id, db, data.provider, data.model
    )

    user_content = data.content
    if data.instructions:
        user_content += f"\n\n---\nAdditional instructions: {data.instructions}"

    messages = [
        {"role": "system", "content": IMPROVE_PROMPT_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    try:
        result = llm_service.generate_response(
            messages=messages,
            llm_provider=provider_enum,
            llm_model=model_str,
            organization_id=organization_id,
            db=db,
            temperature=0.3,
            max_tokens=4000,
        )
        return {"content": result["text"], "provider": provider_enum.value, "model": model_str}
    except Exception as e:
        logger.error(f"[PromptPartials] AI improve failed: {repr(e)}")
        raise HTTPException(500, f"AI improve failed: {str(e)}")


@router.post("", response_model=PromptPartialResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt_partial(
    data: PromptPartialCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Create a new prompt partial with its initial version."""
    try:
        partial = PromptPartial(
            organization_id=organization_id,
            name=data.name,
            description=data.description,
            content=data.content,
            tags=data.tags,
            current_version=1,
        )
        db.add(partial)
        db.flush()

        version = PromptPartialVersion(
            prompt_partial_id=partial.id,
            version=1,
            content=data.content,
            change_summary="Initial version",
        )
        db.add(version)
        db.commit()
        db.refresh(partial)
        return partial
    except IntegrityError as e:
        db.rollback()
        if "unique constraint" in str(e.orig).lower() or "duplicate key" in str(e.orig).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A prompt partial with this name already exists",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Database constraint violation")
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {str(e)}")


@router.get("", response_model=List[PromptPartialResponse])
async def list_prompt_partials(
    skip: int = 0,
    limit: int = 100,
    search: str = Query(None, description="Search by name or description"),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List all prompt partials for the organization."""
    try:
        query = db.query(PromptPartial).filter(PromptPartial.organization_id == organization_id)
        if search:
            query = query.filter(
                PromptPartial.name.ilike(f"%{search}%") | PromptPartial.description.ilike(f"%{search}%")
            )
        query = query.order_by(PromptPartial.updated_at.desc())
        return query.offset(skip).limit(limit).all()
    except SQLAlchemyError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {str(e)}")


@router.get("/{partial_id}", response_model=PromptPartialDetailResponse)
async def get_prompt_partial(
    partial_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get a specific prompt partial with its version history."""
    try:
        partial = (
            db.query(PromptPartial)
            .filter(PromptPartial.id == partial_id, PromptPartial.organization_id == organization_id)
            .first()
        )
        if not partial:
            raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")
        return partial
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {str(e)}")


@router.put("/{partial_id}", response_model=PromptPartialResponse)
async def update_prompt_partial(
    partial_id: UUID,
    data: PromptPartialUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Update a prompt partial. If content changes, a new version is automatically created."""
    try:
        partial = (
            db.query(PromptPartial)
            .filter(PromptPartial.id == partial_id, PromptPartial.organization_id == organization_id)
            .first()
        )
        if not partial:
            raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")

        update_data = data.model_dump(exclude_unset=True)
        content_changed = "content" in update_data and update_data["content"] != partial.content
        change_summary = update_data.pop("change_summary", None)

        for field, value in update_data.items():
            setattr(partial, field, value)

        if content_changed:
            new_version_num = partial.current_version + 1
            version = PromptPartialVersion(
                prompt_partial_id=partial.id,
                version=new_version_num,
                content=update_data["content"],
                change_summary=change_summary or f"Updated to version {new_version_num}",
            )
            db.add(version)
            partial.current_version = new_version_num

        db.commit()
        db.refresh(partial)
        return partial
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        if "unique constraint" in str(e.orig).lower() or "duplicate key" in str(e.orig).lower():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A prompt partial with this name already exists")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Database constraint violation")
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {str(e)}")


@router.delete("/{partial_id}")
async def delete_prompt_partial(
    partial_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete a prompt partial and all its versions."""
    partial = (
        db.query(PromptPartial)
        .filter(PromptPartial.id == partial_id, PromptPartial.organization_id == organization_id)
        .first()
    )
    if not partial:
        raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")

    db.delete(partial)
    db.commit()
    return JSONResponse(status_code=204, content=None)


@router.get("/{partial_id}/versions", response_model=List[PromptPartialVersionResponse])
async def list_prompt_partial_versions(
    partial_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List all versions of a prompt partial."""
    partial = (
        db.query(PromptPartial)
        .filter(PromptPartial.id == partial_id, PromptPartial.organization_id == organization_id)
        .first()
    )
    if not partial:
        raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")

    versions = (
        db.query(PromptPartialVersion)
        .filter(PromptPartialVersion.prompt_partial_id == partial_id)
        .order_by(PromptPartialVersion.version.desc())
        .all()
    )
    return versions


@router.get("/{partial_id}/versions/{version_number}", response_model=PromptPartialVersionResponse)
async def get_prompt_partial_version(
    partial_id: UUID,
    version_number: int,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get a specific version of a prompt partial."""
    partial = (
        db.query(PromptPartial)
        .filter(PromptPartial.id == partial_id, PromptPartial.organization_id == organization_id)
        .first()
    )
    if not partial:
        raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")

    version = (
        db.query(PromptPartialVersion)
        .filter(
            PromptPartialVersion.prompt_partial_id == partial_id,
            PromptPartialVersion.version == version_number,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail=f"Version {version_number} not found")
    return version


@router.post("/{partial_id}/revert/{version_number}", response_model=PromptPartialResponse)
async def revert_prompt_partial(
    partial_id: UUID,
    version_number: int,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Revert a prompt partial to a specific version. Creates a new version with the old content."""
    try:
        partial = (
            db.query(PromptPartial)
            .filter(PromptPartial.id == partial_id, PromptPartial.organization_id == organization_id)
            .first()
        )
        if not partial:
            raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")

        target_version = (
            db.query(PromptPartialVersion)
            .filter(
                PromptPartialVersion.prompt_partial_id == partial_id,
                PromptPartialVersion.version == version_number,
            )
            .first()
        )
        if not target_version:
            raise HTTPException(status_code=404, detail=f"Version {version_number} not found")

        if partial.content == target_version.content:
            return partial

        new_version_num = partial.current_version + 1
        version = PromptPartialVersion(
            prompt_partial_id=partial.id,
            version=new_version_num,
            content=target_version.content,
            change_summary=f"Reverted to version {version_number}",
        )
        db.add(version)
        partial.content = target_version.content
        partial.current_version = new_version_num

        db.commit()
        db.refresh(partial)
        return partial
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {str(e)}")


@router.post("/{partial_id}/clone", response_model=PromptPartialResponse, status_code=status.HTTP_201_CREATED)
async def clone_prompt_partial(
    partial_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Clone a prompt partial."""
    try:
        source = (
            db.query(PromptPartial)
            .filter(PromptPartial.id == partial_id, PromptPartial.organization_id == organization_id)
            .first()
        )
        if not source:
            raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")

        clone = PromptPartial(
            organization_id=organization_id,
            name=f"{source.name} (Copy)",
            description=source.description,
            content=source.content,
            tags=source.tags,
            current_version=1,
        )
        db.add(clone)
        db.flush()

        version = PromptPartialVersion(
            prompt_partial_id=clone.id,
            version=1,
            content=source.content,
            change_summary=f"Cloned from '{source.name}'",
        )
        db.add(version)
        db.commit()
        db.refresh(clone)
        return clone
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Database constraint violation")
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {str(e)}")
