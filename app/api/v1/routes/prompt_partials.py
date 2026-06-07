"""
Prompt Partials API Routes
CRUD operations with version history for reusable prompt templates.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from loguru import logger

from app.dependencies import get_db, get_organization_id, get_workspace_id, get_api_key
from app.models.database import PromptPartial, PromptPartialVersion
from app.models.schemas import (
    AgentFlowGraph,
    AgentFlowNode,
    AgentFlowLayoutSaveRequest,
    PromptPartialCreate,
    PromptPartialUpdate,
    PromptPartialResponse,
    PromptPartialDetailResponse,
    PromptPartialVersionResponse,
)
from app.services.imported_agent_constants import IMPORTED_AGENT_TAG

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


class GenerateFlowchartRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    regenerate: bool = False


class NodePromptMapRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None


def _partial_has_imported_agent_tag(tags: Optional[list]) -> bool:
    return isinstance(tags, list) and IMPORTED_AGENT_TAG in tags


def _flowchart_for_response(partial: PromptPartial) -> Optional[dict]:
    """Return agent_flowchart with stale prompt mappings stripped for display."""
    if not isinstance(partial.agent_flowchart, dict) or not partial.agent_flowchart.get("nodes"):
        return partial.agent_flowchart
    from app.services.agent_flowchart import apply_prompt_hash_staleness

    graph = AgentFlowGraph.model_validate(partial.agent_flowchart)
    return apply_prompt_hash_staleness(graph, partial.content).model_dump(mode="json")


def _agent_flowchart_response(partial: PromptPartial) -> AgentFlowGraph:
    """Build API flowchart payload from the current partial row."""
    raw = _flowchart_for_response(partial)
    if isinstance(raw, dict) and raw.get("nodes"):
        return AgentFlowGraph.model_validate(raw)
    return AgentFlowGraph()


def _apply_prompt_partial_kind_filter(query, kind: Optional[str]):
    """Filter list results by imported-agent vs regular partial."""
    from sqlalchemy import cast, or_
    from sqlalchemy.dialects.postgresql import JSONB

    normalized = (kind or "all").strip().lower()
    tag_json = cast([IMPORTED_AGENT_TAG], JSONB)
    tags_col = cast(PromptPartial.tags, JSONB)
    if normalized == "imported_agent":
        return query.filter(tags_col.contains(tag_json))
    if normalized == "partial":
        return query.filter(
            or_(PromptPartial.tags.is_(None), ~tags_col.contains(tag_json))
        )
    return query


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


# Resolver moved to app/services/ai/llm_resolver.py so the call-import
# evaluation insights endpoint can share the exact same auto-detect /
# default-model behavior as the prompt-partials AI flows. We re-export
# under the original name for backwards compatibility with any external
# patches in tests.
from app.services.ai.llm_resolver import (
    get_llm_provider_and_model as _get_llm_provider_and_model,
)


@router.post("/generate")
async def generate_prompt_with_ai(
    data: GeneratePromptRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Generate a new prompt using AI from a description."""
    from app.services.ai.llm_service import llm_service

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
    from app.services.ai.llm_service import llm_service

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
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Create a prompt partial in the active workspace with its initial version."""
    try:
        partial = PromptPartial(
            organization_id=organization_id,
            workspace_id=workspace_id,
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
            workspace_id=workspace_id,
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
    kind: str = Query(
        "all",
        description="Filter by kind: all, partial (exclude imported agents), imported_agent",
    ),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """List prompt partials in the active workspace."""
    try:
        query = db.query(PromptPartial).filter(
            PromptPartial.organization_id == organization_id,
            PromptPartial.workspace_id == workspace_id,
        )
        query = _apply_prompt_partial_kind_filter(query, kind)
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
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Get a prompt partial (and its version history) from the active workspace."""
    try:
        partial = (
            db.query(PromptPartial)
            .filter(
                PromptPartial.id == partial_id,
                PromptPartial.organization_id == organization_id,
                PromptPartial.workspace_id == workspace_id,
            )
            .first()
        )
        if not partial:
            raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")
        if isinstance(partial.agent_flowchart, dict):
            partial.agent_flowchart = _flowchart_for_response(partial)
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
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Update a prompt partial in the active workspace. New versions inherit the workspace."""
    try:
        partial = (
            db.query(PromptPartial)
            .filter(
                PromptPartial.id == partial_id,
                PromptPartial.organization_id == organization_id,
                PromptPartial.workspace_id == workspace_id,
            )
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
                workspace_id=partial.workspace_id,
                version=new_version_num,
                content=update_data["content"],
                change_summary=change_summary or f"Updated to version {new_version_num}",
            )
            db.add(version)
            partial.current_version = new_version_num
            if isinstance(partial.agent_flowchart, dict) and partial.agent_flowchart.get("nodes"):
                from app.services.agent_flowchart import strip_node_prompt_mappings
                from sqlalchemy.orm.attributes import flag_modified

                graph = AgentFlowGraph.model_validate(partial.agent_flowchart)
                partial.agent_flowchart = strip_node_prompt_mappings(graph).model_dump(
                    mode="json"
                )
                flag_modified(partial, "agent_flowchart")

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
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Delete a prompt partial (and its versions) from the active workspace."""
    partial = (
        db.query(PromptPartial)
        .filter(
            PromptPartial.id == partial_id,
            PromptPartial.organization_id == organization_id,
            PromptPartial.workspace_id == workspace_id,
        )
        .first()
    )
    if not partial:
        raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")

    db.delete(partial)
    db.commit()
    return Response(status_code=204)


@router.get("/{partial_id}/versions", response_model=List[PromptPartialVersionResponse])
async def list_prompt_partial_versions(
    partial_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """List all versions of a prompt partial in the active workspace."""
    partial = (
        db.query(PromptPartial)
        .filter(
            PromptPartial.id == partial_id,
            PromptPartial.organization_id == organization_id,
            PromptPartial.workspace_id == workspace_id,
        )
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
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Get a specific version of a prompt partial in the active workspace."""
    partial = (
        db.query(PromptPartial)
        .filter(
            PromptPartial.id == partial_id,
            PromptPartial.organization_id == organization_id,
            PromptPartial.workspace_id == workspace_id,
        )
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
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Revert a prompt partial (in the active workspace) to a specific version."""
    try:
        partial = (
            db.query(PromptPartial)
            .filter(
                PromptPartial.id == partial_id,
                PromptPartial.organization_id == organization_id,
                PromptPartial.workspace_id == workspace_id,
            )
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
            workspace_id=partial.workspace_id,
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
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Clone a prompt partial within the active workspace."""
    try:
        source = (
            db.query(PromptPartial)
            .filter(
                PromptPartial.id == partial_id,
                PromptPartial.organization_id == organization_id,
                PromptPartial.workspace_id == workspace_id,
            )
            .first()
        )
        if not source:
            raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")

        clone = PromptPartial(
            organization_id=organization_id,
            workspace_id=workspace_id,
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
            workspace_id=workspace_id,
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


@router.post("/{partial_id}/flowchart", response_model=AgentFlowGraph)
async def generate_prompt_partial_flowchart(
    partial_id: UUID,
    data: GenerateFlowchartRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Generate (or return cached) agent logic flowchart for an imported agent."""
    from app.workers.tasks.agent_flowchart_jobs import generate_agent_flowchart_task

    partial = (
        db.query(PromptPartial)
        .filter(
            PromptPartial.id == partial_id,
            PromptPartial.organization_id == organization_id,
            PromptPartial.workspace_id == workspace_id,
        )
        .first()
    )
    if not partial:
        raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")
    if not _partial_has_imported_agent_tag(partial.tags):
        raise HTTPException(
            status_code=400,
            detail="Flowchart generation is only available for imported agents",
        )

    if (
        not data.regenerate
        and partial.agent_flowchart_status == "completed"
        and isinstance(partial.agent_flowchart, dict)
        and partial.agent_flowchart.get("nodes")
    ):
        from app.services.agent_flowchart import apply_prompt_hash_staleness

        return _agent_flowchart_response(partial)

    if partial.agent_flowchart_status in {"generating", "mapping"}:
        return _agent_flowchart_response(partial)

    from sqlalchemy.orm.attributes import flag_modified

    partial.agent_flowchart_status = "generating"
    if isinstance(partial.agent_flowchart, dict):
        partial.agent_flowchart = {
            **partial.agent_flowchart,
            "generation_error": None,
        }
        flag_modified(partial, "agent_flowchart")
    db.commit()

    generate_agent_flowchart_task.apply_async(
        kwargs={
            "partial_id": str(partial.id),
            "provider": data.provider,
            "model": data.model,
        },
        queue="imports",
    )
    db.refresh(partial)
    return _agent_flowchart_response(partial)


@router.put("/{partial_id}/flowchart/layout", response_model=AgentFlowGraph)
async def save_prompt_partial_flowchart_layout(
    partial_id: UUID,
    data: AgentFlowLayoutSaveRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Persist user-adjusted node positions for an imported agent flowchart."""
    from datetime import datetime, timezone

    from app.services.agent_flowchart import apply_prompt_hash_staleness

    partial = (
        db.query(PromptPartial)
        .filter(
            PromptPartial.id == partial_id,
            PromptPartial.organization_id == organization_id,
            PromptPartial.workspace_id == workspace_id,
        )
        .first()
    )
    if not partial:
        raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")
    if not _partial_has_imported_agent_tag(partial.tags):
        raise HTTPException(
            status_code=400,
            detail="Layout save is only available for imported agents",
        )
    if not isinstance(partial.agent_flowchart, dict) or not partial.agent_flowchart.get("nodes"):
        raise HTTPException(status_code=400, detail="Generate a flowchart before saving layout")

    position_by_id = {
        item.id: (item.position_x, item.position_y) for item in data.nodes
    }
    nodes_raw = partial.agent_flowchart.get("nodes")
    if not isinstance(nodes_raw, list):
        raise HTTPException(status_code=400, detail="Invalid cached flowchart")

    updated_nodes = []
    for node in nodes_raw:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        if node_id in position_by_id:
            pos_x, pos_y = position_by_id[node_id]
            node = {
                **node,
                "position_x": pos_x,
                "position_y": pos_y,
            }
        updated_nodes.append(node)

    from sqlalchemy.orm.attributes import flag_modified

    partial.agent_flowchart = {
        **partial.agent_flowchart,
        "nodes": updated_nodes,
        "layout_saved_at": datetime.now(timezone.utc).isoformat(),
    }
    flag_modified(partial, "agent_flowchart")
    db.commit()
    db.refresh(partial)
    return apply_prompt_hash_staleness(
        AgentFlowGraph.model_validate(partial.agent_flowchart),
        partial.content,
    )


@router.post("/{partial_id}/flowchart/prompt-map", response_model=AgentFlowGraph)
async def map_prompt_partial_flowchart_nodes(
    partial_id: UUID,
    data: NodePromptMapRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Enqueue batch mapping of prompt excerpts for all flowchart nodes."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.workers.tasks.agent_flowchart_jobs import (
        map_agent_flowchart_prompt_sections_task,
    )

    partial = (
        db.query(PromptPartial)
        .filter(
            PromptPartial.id == partial_id,
            PromptPartial.organization_id == organization_id,
            PromptPartial.workspace_id == workspace_id,
        )
        .first()
    )
    if not partial:
        raise HTTPException(status_code=404, detail=f"Prompt partial {partial_id} not found")
    if not _partial_has_imported_agent_tag(partial.tags):
        raise HTTPException(
            status_code=400,
            detail="Node prompt mapping is only available for imported agents",
        )
    if not isinstance(partial.agent_flowchart, dict) or not partial.agent_flowchart.get("nodes"):
        raise HTTPException(status_code=400, detail="Generate a flowchart before mapping nodes")
    if partial.agent_flowchart_status == "generating":
        raise HTTPException(
            status_code=409,
            detail="Flowchart is still generating. Try again once generation completes.",
        )
    if partial.agent_flowchart_status == "mapping":
        return _agent_flowchart_response(partial)

    partial.agent_flowchart_status = "mapping"
    if isinstance(partial.agent_flowchart, dict):
        partial.agent_flowchart = {
            **partial.agent_flowchart,
            "mapping_error": None,
        }
        flag_modified(partial, "agent_flowchart")
    db.commit()

    map_agent_flowchart_prompt_sections_task.apply_async(
        kwargs={
            "partial_id": str(partial.id),
            "provider": data.provider,
            "model": data.model,
        },
        queue="imports",
    )
    db.refresh(partial)
    return _agent_flowchart_response(partial)
