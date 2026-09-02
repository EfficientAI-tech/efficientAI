"""
Agents API Routes
Complete CRUD operations for test agents
"""
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID, uuid4
import random
from pydantic import BaseModel
from loguru import logger

from app.dependencies import get_db, get_organization_id, get_workspace_id, get_api_key
from app.services.billing.flexprice_service import record_agent_test_setup_generated
from app.models.database import (
    Agent, ConversationEvaluation, TestAgentConversation, VoiceBundle,
    AIProvider, Integration, IntegrationPlatform, CallMediumEnum,
    Evaluator, EvaluatorResult, CallRecording, Scenario,
)
from sqlalchemy import and_
from app.models.schemas import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentPhoneAssignmentCheckResponse,
    AgentPhoneAssignmentConflict,
    CallMediumEnum as CallMediumEnumSchema,
    GenerateTestPromptRequest,
    GenerateTestPromptResponse,
    GenerateScenariosFromPromptRequest,
    GenerateScenariosFromPromptResponse,
    GenerateTestSetupRequest,
    GenerateTestSetupResponse,
    GeneratedScenarioDraftResponse,
    TestPromptSectionResponse,
    TestAgentFirstMessageResponse,
    TestAgentTemplateResponse,
    TestAgentTemplateInput,
)
from app.services.testing.test_agent_template import (
    TestAgentFirstMessage,
    TestAgentTemplate,
    assemble_test_agent_prompt,
    normalize_first_message,
    normalize_sections,
    template_from_generation,
)

router = APIRouter(prefix="/agents", tags=["agents"])


def _first_message_response(first_message: TestAgentFirstMessage) -> TestAgentFirstMessageResponse:
    return TestAgentFirstMessageResponse(
        production_mode=first_message.production_mode,
        production_message=first_message.production_message,
        caller_mode=first_message.caller_mode,
        caller_message=first_message.caller_message,
    )


def _template_response(template: TestAgentTemplate) -> TestAgentTemplateResponse:
    return TestAgentTemplateResponse(
        sections=_test_prompt_section_responses(template.sections),
        first_message=_first_message_response(template.first_message),
    )


def _template_input_to_storage(template_input: TestAgentTemplateInput) -> dict:
    sections = normalize_sections([s.model_dump() for s in template_input.sections])
    first_message = normalize_first_message(template_input.first_message.model_dump())
    return template_from_generation(sections, first_message).to_dict()


def _apply_test_agent_template_fields(
    *,
    description: Optional[str],
    template_input: Optional[TestAgentTemplateInput],
) -> tuple[Optional[str], Optional[dict]]:
    """Return (description, test_agent_template_json) for persistence."""
    if template_input is None:
        return description, None
    template_dict = _template_input_to_storage(template_input)
    assembled = assemble_test_agent_prompt(normalize_sections(template_dict.get("sections")))
    return assembled or description, template_dict


def _validate_agent_phone_assignment(
    db: Session,
    *,
    organization_id: UUID,
    call_medium,
    phone_number: Optional[str],
    telephony_phone_number_id: Optional[UUID],
    exclude_agent_id: Optional[UUID] = None,
) -> None:
    """Raise HTTPException if phone assignment conflicts with another agent."""
    if call_medium != CallMediumEnum.PHONE_CALL:
        return
    if not phone_number and not telephony_phone_number_id:
        return

    from app.services.telephony.phone_routing import find_agent_phone_assignment_conflict

    conflict = find_agent_phone_assignment_conflict(
        db,
        organization_id=organization_id,
        phone_number=phone_number,
        telephony_phone_number_id=telephony_phone_number_id,
        exclude_agent_id=exclude_agent_id,
    )
    if not conflict:
        return
    if conflict.get("error") == "telephony_not_found":
        raise HTTPException(status_code=404, detail="Telephony phone number not found")

    agent_name = conflict["agent_name"]
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": f'This number is already assigned to agent "{agent_name}".',
            "agent_id": str(conflict["agent_id"]),
            "agent_name": agent_name,
            "phone_number": conflict["phone_number"],
        },
    )


def resolve_agent_by_path_id(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: str,
) -> Agent:
    """Resolve agent by UUID primary key or 6-digit agent_id (same as GET /agents/{id})."""
    try:
        agent_uuid = UUID(agent_id)
        agent = db.query(Agent).filter(
            and_(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        agent = db.query(Agent).filter(
            and_(
                Agent.agent_id == agent_id,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent


# ======================================================================
# AI Generation for agent descriptions
# ======================================================================

class GenerateAgentDescriptionRequest(BaseModel):
    description: str
    tone: Optional[str] = "professional"
    format_style: Optional[str] = "structured"
    provider: Optional[str] = None
    model: Optional[str] = None
    agent_id: Optional[UUID] = None
    include_linked_scenarios: bool = True
    append_scenarios_to_output: bool = False


GENERATE_AGENT_DESCRIPTION_SYSTEM = (
    "You are an expert at writing clear, well-structured descriptions for voice AI test agents. "
    "The user will describe what they need the agent to do, and you will generate a comprehensive, "
    "well-formatted agent description in markdown.\n\n"
    "Guidelines:\n"
    "- Use clear markdown structure: headings, bullet points, numbered lists\n"
    "- Include sections for: Role and Goal, Talking Style, Questions to Ask, Information to Relay, and Constraints\n"
    "- Be specific about the agent's role, tone of voice, and how it should handle conversations\n"
    "- Include example scenarios or edge cases where helpful\n"
    "- Return ONLY the description in markdown, no preamble or explanation about what you did"
)


from app.services.ai.llm_resolver import get_llm_provider_and_model as _get_llm_provider_and_model


@router.post("/generate-description")
async def generate_agent_description(
    data: GenerateAgentDescriptionRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Generate an agent description using AI from a brief description."""
    from contextlib import nullcontext

    from app.services.ai.llm_service import llm_service
    from app.services.usage.context import llm_usage_context, usage_context_for_agent
    from app.services.testing.test_agent_simulation_prompt import (
        format_scenarios_for_generation_context,
        format_scenarios_reference_appendix,
        load_linked_scenarios_for_agent,
        merge_generated_description_with_scenario_appendix,
    )

    if not data.description.strip():
        raise HTTPException(400, "Description is required")

    provider_enum, model_str = _get_llm_provider_and_model(
        organization_id, db, data.provider, data.model
    )

    linked_scenarios = []
    if data.agent_id and data.include_linked_scenarios:
        agent = db.query(Agent).filter(
            Agent.id == data.agent_id,
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
        ).first()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {data.agent_id} not found")
        linked_scenarios = load_linked_scenarios_for_agent(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_id=agent.id,
        )

    user_prompt_parts = [
        "Create a detailed agent description for the following:",
        "",
        f"Description: {data.description}",
        f"Tone: {data.tone or 'professional'}",
        f"Format: {data.format_style or 'structured'}",
    ]
    scenario_context = format_scenarios_for_generation_context(linked_scenarios)
    if scenario_context:
        user_prompt_parts.extend(["", scenario_context])
    user_prompt_parts.extend([
        "",
        "Generate a comprehensive, well-formatted agent description in markdown.",
    ])
    user_prompt = "\n".join(user_prompt_parts)

    messages = [
        {"role": "system", "content": GENERATE_AGENT_DESCRIPTION_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    try:
        usage_ctx = nullcontext()
        if data.agent_id:
            agent_for_usage = db.query(Agent).filter(
                Agent.id == data.agent_id,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            ).first()
            if agent_for_usage:
                usage_ctx = llm_usage_context(
                    usage_context_for_agent(agent_for_usage, workspace_id=workspace_id)
                )

        with usage_ctx:
            result = llm_service.generate_response(
                messages=messages,
                llm_provider=provider_enum,
                llm_model=model_str,
                organization_id=organization_id,
                db=db,
                temperature=0.7,
                max_tokens=4000,
            )
        content = result["text"]
        if data.append_scenarios_to_output and linked_scenarios:
            appendix = format_scenarios_reference_appendix(linked_scenarios)
            content = merge_generated_description_with_scenario_appendix(content, appendix)
        return {"content": content, "provider": provider_enum.value, "model": model_str}
    except Exception as e:
        logger.error(f"[Agents] AI description generation failed: {repr(e)}")
        raise HTTPException(500, f"AI generation failed: {str(e)}")


def _test_prompt_section_responses(sections) -> list[TestPromptSectionResponse]:
    return [
        TestPromptSectionResponse(key=s.key, title=s.title, content=s.content)
        for s in sections
    ]


def _scenario_draft_responses(scenarios) -> list[GeneratedScenarioDraftResponse]:
    return [
        GeneratedScenarioDraftResponse(name=s.name, description=s.description, goal=s.goal)
        for s in scenarios
    ]


@router.post("/generate-test-prompt", response_model=GenerateTestPromptResponse)
async def generate_test_prompt(
    data: GenerateTestPromptRequest,
    background_tasks: BackgroundTasks,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Stage 1: generate foundational test agent prompt from production prompt."""
    from app.services.testing.agent_test_setup_generation import (
        generate_test_prompt_from_production,
    )
    from app.services.usage.context import (
        LLMUsageContext,
        LLMUsageProductSection,
        llm_usage_context,
    )

    if not data.production_prompt.strip():
        raise HTTPException(400, "Production prompt is required")

    provider_enum, model_str = _get_llm_provider_and_model(
        organization_id, db, data.provider, data.model, data.credential_id
    )

    try:
        with llm_usage_context(
            LLMUsageContext(
                organization_id=organization_id,
                workspace_id=workspace_id,
                product_section=LLMUsageProductSection.AGENTS,
            )
        ):
            result = generate_test_prompt_from_production(
                data.production_prompt,
                agent_name=data.agent_name,
                language=data.language,
                call_type=data.call_type,
                additional_context=data.additional_context,
                llm_provider=provider_enum,
                llm_model=model_str,
                organization_id=organization_id,
                db=db,
                llm_config=data.llm_config,
                credential_id=data.credential_id,
            )
        background_tasks.add_task(
            record_agent_test_setup_generated,
            organization_id,
            uuid4(),
            workspace_id=workspace_id,
            purpose="test_prompt",
            model=result.model,
        )
        return GenerateTestPromptResponse(
            sections=_test_prompt_section_responses(result.sections),
            test_agent_prompt=result.test_agent_prompt,
            first_message=_first_message_response(result.first_message),
            test_agent_template=_template_response(result.test_agent_template),
            provider=result.provider,
            model=result.model,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.error(f"[Agents] Test prompt generation failed: {repr(e)}")
        raise HTTPException(500, f"AI generation failed: {str(e)}") from e


@router.post("/generate-scenarios-from-prompt", response_model=GenerateScenariosFromPromptResponse)
async def generate_scenarios_from_prompt(
    data: GenerateScenariosFromPromptRequest,
    background_tasks: BackgroundTasks,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Stage 2: generate scenario drafts from a test agent prompt."""
    from app.services.testing.agent_test_setup_generation import (
        generate_scenarios_from_test_prompt,
    )
    from app.services.usage.context import (
        LLMUsageContext,
        LLMUsageProductSection,
        llm_usage_context,
    )

    if not data.test_agent_prompt.strip():
        raise HTTPException(400, "Test agent prompt is required")

    provider_enum, model_str = _get_llm_provider_and_model(
        organization_id, db, data.provider, data.model, data.credential_id
    )

    try:
        with llm_usage_context(
            LLMUsageContext(
                organization_id=organization_id,
                workspace_id=workspace_id,
                product_section=LLMUsageProductSection.AGENTS,
            )
        ):
            result = generate_scenarios_from_test_prompt(
                data.test_agent_prompt,
                agent_name=data.agent_name,
                scenario_count=data.scenario_count,
                language=data.language,
                call_type=data.call_type,
                additional_context=data.additional_context,
                llm_provider=provider_enum,
                llm_model=model_str,
                organization_id=organization_id,
                db=db,
                llm_config=data.llm_config,
                credential_id=data.credential_id,
            )
        background_tasks.add_task(
            record_agent_test_setup_generated,
            organization_id,
            uuid4(),
            workspace_id=workspace_id,
            purpose="scenarios",
            model=result.model,
            scenario_count=len(result.scenarios),
        )
        return GenerateScenariosFromPromptResponse(
            scenarios=_scenario_draft_responses(result.scenarios),
            provider=result.provider,
            model=result.model,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.error(f"[Agents] Scenario generation failed: {repr(e)}")
        raise HTTPException(500, f"AI generation failed: {str(e)}") from e


@router.post("/generate-test-setup", response_model=GenerateTestSetupResponse)
async def generate_test_setup(
    data: GenerateTestSetupRequest,
    background_tasks: BackgroundTasks,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Run stage 1 then stage 2: foundational test prompt + scenario drafts."""
    from app.services.testing.agent_test_setup_generation import (
        generate_scenarios_from_test_prompt,
        generate_test_prompt_from_production,
    )
    from app.services.usage.context import (
        LLMUsageContext,
        LLMUsageProductSection,
        llm_usage_context,
    )

    if not data.production_prompt.strip():
        raise HTTPException(400, "Production prompt is required")

    provider_enum, model_str = _get_llm_provider_and_model(
        organization_id, db, data.provider, data.model, data.credential_id
    )

    try:
        with llm_usage_context(
            LLMUsageContext(
                organization_id=organization_id,
                workspace_id=workspace_id,
                product_section=LLMUsageProductSection.AGENTS,
            )
        ):
            prompt_result = generate_test_prompt_from_production(
                data.production_prompt,
                agent_name=data.agent_name,
                language=data.language,
                call_type=data.call_type,
                additional_context=data.additional_context,
                llm_provider=provider_enum,
                llm_model=model_str,
                organization_id=organization_id,
                db=db,
                llm_config=data.llm_config,
                credential_id=data.credential_id,
            )
            scenario_result = generate_scenarios_from_test_prompt(
                prompt_result.test_agent_prompt,
                agent_name=data.agent_name,
                scenario_count=data.scenario_count,
                language=data.language,
                call_type=data.call_type,
                additional_context=data.additional_context,
                llm_provider=provider_enum,
                llm_model=model_str,
                organization_id=organization_id,
                db=db,
                llm_config=data.llm_config,
                credential_id=data.credential_id,
            )
        background_tasks.add_task(
            record_agent_test_setup_generated,
            organization_id,
            uuid4(),
            workspace_id=workspace_id,
            purpose="full_setup",
            model=scenario_result.model,
            scenario_count=len(scenario_result.scenarios),
        )
        return GenerateTestSetupResponse(
            sections=_test_prompt_section_responses(prompt_result.sections),
            test_agent_prompt=prompt_result.test_agent_prompt,
            first_message=_first_message_response(prompt_result.first_message),
            test_agent_template=_template_response(prompt_result.test_agent_template),
            scenarios=_scenario_draft_responses(scenario_result.scenarios),
            provider=prompt_result.provider,
            model=prompt_result.model,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.error(f"[Agents] Test setup generation failed: {repr(e)}")
        raise HTTPException(500, f"AI generation failed: {str(e)}") from e


def generate_unique_agent_id(db: Session) -> str:
    """Generate a unique 6-digit agent ID."""
    max_attempts = 100
    for _ in range(max_attempts):
        agent_id = f"{random.randint(100000, 999999)}"
        existing = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if not existing:
            return agent_id
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to generate unique agent ID"
    )


def get_agent_dependencies(db: Session, organization_id: UUID, agent_uuid: UUID) -> dict:
    """Return dependency counts that block non-force delete."""
    evaluators_count = db.query(Evaluator).filter(
        Evaluator.agent_id == agent_uuid,
        Evaluator.organization_id == organization_id,
    ).count()

    evaluator_results_count = db.query(EvaluatorResult).filter(
        EvaluatorResult.agent_id == agent_uuid,
        EvaluatorResult.organization_id == organization_id,
    ).count()

    call_recordings_count = db.query(CallRecording).filter(
        CallRecording.agent_id == agent_uuid,
        CallRecording.organization_id == organization_id,
    ).count()

    conversation_evaluations_count = db.query(ConversationEvaluation).filter(
        ConversationEvaluation.agent_id == agent_uuid,
        ConversationEvaluation.organization_id == organization_id,
    ).count()

    test_conversations_count = db.query(TestAgentConversation).filter(
        TestAgentConversation.agent_id == agent_uuid,
        TestAgentConversation.organization_id == organization_id,
    ).count()

    dependencies = {}
    if evaluators_count > 0:
        dependencies["evaluators"] = evaluators_count
    if evaluator_results_count > 0:
        dependencies["evaluator_results"] = evaluator_results_count
    if call_recordings_count > 0:
        dependencies["call_recordings"] = call_recordings_count
    if conversation_evaluations_count > 0:
        dependencies["conversation_evaluations"] = conversation_evaluations_count
    if test_conversations_count > 0:
        dependencies["test_conversations"] = test_conversations_count

    return dependencies


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    agent: AgentCreate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Create a new test agent.

    The agent is stamped with the active workspace from the
    ``X-Workspace-Id`` header (falling back to the org's Default).
    """
    # Validate phone_number is provided when call_medium is phone_call
    if agent.call_medium == CallMediumEnumSchema.PHONE_CALL and not agent.phone_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="phone_number is required when call_medium is phone_call"
        )
    
    # Validate voice_bundle_id exists, is active, and belongs to organization
    voice_bundle = db.query(VoiceBundle).filter(
        and_(
            VoiceBundle.id == agent.voice_bundle_id,
            VoiceBundle.organization_id == organization_id,
            VoiceBundle.is_active == True,
        )
    ).first()
    if not voice_bundle:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active voice bundle not found",
        )
    
    # Validate voice_ai_integration_id exists and belongs to organization
    if agent.voice_ai_integration_id:
        integration = db.query(Integration).filter(
            and_(
                Integration.id == agent.voice_ai_integration_id,
                Integration.organization_id == organization_id,
                Integration.is_active == True
            )
        ).first()
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found or inactive")
        
        if integration.platform not in [
            IntegrationPlatform.RETELL,
            IntegrationPlatform.VAPI,
            IntegrationPlatform.ELEVENLABS,
            IntegrationPlatform.SMALLEST,
        ]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Integration platform {integration.platform.value} is not supported for Voice AI agents. "
                    "Only Retell, Vapi, ElevenLabs, and Smallest are supported."
                )
            )
        
        if not agent.voice_ai_agent_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="voice_ai_agent_id is required when voice_ai_integration_id is provided"
            )

    _validate_agent_phone_assignment(
        db,
        organization_id=organization_id,
        call_medium=agent.call_medium,
        phone_number=agent.phone_number,
        telephony_phone_number_id=agent.telephony_phone_number_id,
    )

    # Generate unique 6-digit agent_id
    agent_id = generate_unique_agent_id(db)

    description, template_dict = _apply_test_agent_template_fields(
        description=agent.description,
        template_input=agent.test_agent_template,
    )
    
    db_agent = Agent(
        agent_id=agent_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=agent.name,
        phone_number=agent.phone_number,
        language=agent.language,
        description=description,
        test_agent_template=template_dict,
        call_type=agent.call_type,
        call_medium=agent.call_medium,
        telephony_phone_number_id=agent.telephony_phone_number_id,
        voice_bundle_id=agent.voice_bundle_id,
        ai_provider_id=agent.ai_provider_id,
        voice_ai_integration_id=agent.voice_ai_integration_id,
        voice_ai_agent_id=agent.voice_ai_agent_id,
        provider_prompt=agent.provider_prompt,
        silence_hangup_secs=agent.silence_hangup_secs,
    )
    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)

    from app.services.telephony.phone_routing import sync_agent_telephony_number_link

    sync_agent_telephony_number_link(db, db_agent)
    db.refresh(db_agent)

    has_provider_prompt = isinstance(agent.provider_prompt, str) and bool(agent.provider_prompt.strip())
    if agent.voice_ai_integration_id and agent.voice_ai_agent_id and not has_provider_prompt:
        try:
            from app.services.voice_providers.prompt_sync import sync_provider_prompt
            integration = db.query(Integration).filter(Integration.id == agent.voice_ai_integration_id).first()
            if integration:
                sync_provider_prompt(db_agent, integration, db)
                db.refresh(db_agent)
        except Exception as e:
            logger.warning(f"[Agents] Best-effort provider prompt sync failed on create: {e}")

    return db_agent


@router.get("", response_model=List[AgentResponse])
async def list_agents(
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Get list of all agents for the active workspace.

    Scoped to (organization_id, workspace_id) so users only see agents
    in the workspace they're currently in.
    """
    agents = db.query(Agent).filter(
        Agent.organization_id == organization_id,
        Agent.workspace_id == workspace_id,
    ).offset(skip).limit(limit).all()
    return agents


@router.get("/check-phone-assignment", response_model=AgentPhoneAssignmentCheckResponse)
async def check_phone_assignment(
    phone_number: Optional[str] = Query(None),
    telephony_phone_number_id: Optional[UUID] = Query(None),
    exclude_agent_id: Optional[UUID] = Query(None),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Check whether a phone number is available for agent assignment in this org."""
    if not phone_number and not telephony_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="phone_number or telephony_phone_number_id is required",
        )

    from app.services.telephony.phone_routing import find_agent_phone_assignment_conflict

    conflict = find_agent_phone_assignment_conflict(
        db,
        organization_id=organization_id,
        phone_number=phone_number,
        telephony_phone_number_id=telephony_phone_number_id,
        exclude_agent_id=exclude_agent_id,
    )
    if conflict and conflict.get("error") == "telephony_not_found":
        raise HTTPException(status_code=404, detail="Telephony phone number not found")
    if conflict:
        return AgentPhoneAssignmentCheckResponse(
            available=False,
            phone_number=conflict["phone_number"],
            conflict=AgentPhoneAssignmentConflict(**conflict),
        )

    resolved_phone = phone_number
    if telephony_phone_number_id:
        from app.models.database import TelephonyPhoneNumber

        row = (
            db.query(TelephonyPhoneNumber)
            .filter(
                TelephonyPhoneNumber.id == telephony_phone_number_id,
                TelephonyPhoneNumber.organization_id == organization_id,
            )
            .first()
        )
        if row:
            resolved_phone = row.phone_number

    return AgentPhoneAssignmentCheckResponse(
        available=True,
        phone_number=resolved_phone,
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Get a specific agent by ID (UUID) or agent_id (6-digit) within the active workspace."""
    try:
        # Try as UUID first
        agent_uuid = UUID(agent_id)
        agent = db.query(Agent).filter(
            and_(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        # Try as 6-digit ID
        agent = db.query(Agent).filter(
            and_(
                Agent.agent_id == agent_id,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()
    
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    agent_update: AgentUpdate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Update an existing agent by ID (UUID) or agent_id (6-digit) within the active workspace."""
    try:
        # Try as UUID first
        agent_uuid = UUID(agent_id)
        db_agent = db.query(Agent).filter(
            and_(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        # Try as 6-digit ID
        db_agent = db.query(Agent).filter(
            and_(
                Agent.agent_id == agent_id,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()
    
    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    # Determine the call_medium to validate
    call_medium = agent_update.call_medium if agent_update.call_medium is not None else db_agent.call_medium
    
    # Validate phone_number is provided when call_medium is phone_call
    if call_medium == CallMediumEnum.PHONE_CALL:
        phone_number = agent_update.phone_number if agent_update.phone_number is not None else db_agent.phone_number
        if not phone_number:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="phone_number is required when call_medium is phone_call"
            )
    
    # Validate voice_bundle_id if provided
    if agent_update.voice_bundle_id:
        voice_bundle = db.query(VoiceBundle).filter(
            and_(
                VoiceBundle.id == agent_update.voice_bundle_id,
                VoiceBundle.organization_id == organization_id
            )
        ).first()
        if not voice_bundle:
            raise HTTPException(status_code=404, detail="Voice bundle not found")
    
    # Validate voice_ai_integration_id if provided
    if agent_update.voice_ai_integration_id:
        integration = db.query(Integration).filter(
            and_(
                Integration.id == agent_update.voice_ai_integration_id,
                Integration.organization_id == organization_id,
                Integration.is_active == True
            )
        ).first()
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found or inactive")
        
        if integration.platform not in [
            IntegrationPlatform.RETELL,
            IntegrationPlatform.VAPI,
            IntegrationPlatform.ELEVENLABS,
            IntegrationPlatform.SMALLEST,
        ]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Integration platform {integration.platform.value} is not supported for Voice AI agents. "
                    "Only Retell, Vapi, ElevenLabs, and Smallest are supported."
                )
            )
        
        if not agent_update.voice_ai_agent_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="voice_ai_agent_id is required when voice_ai_integration_id is provided"
            )

    update_data = agent_update.model_dump(exclude_unset=True, exclude_none=False)

    if "test_agent_template" in update_data:
        template_input = agent_update.test_agent_template
        assembled_description, template_dict = _apply_test_agent_template_fields(
            description=update_data.get("description", db_agent.description),
            template_input=template_input,
        )
        update_data["description"] = assembled_description
        update_data["test_agent_template"] = template_dict

    effective_call_medium = (
        agent_update.call_medium if agent_update.call_medium is not None else db_agent.call_medium
    )
    effective_phone_number = (
        agent_update.phone_number
        if "phone_number" in update_data
        else db_agent.phone_number
    )
    effective_telephony_id = (
        agent_update.telephony_phone_number_id
        if "telephony_phone_number_id" in update_data
        else db_agent.telephony_phone_number_id
    )

    _validate_agent_phone_assignment(
        db,
        organization_id=organization_id,
        call_medium=effective_call_medium,
        phone_number=effective_phone_number,
        telephony_phone_number_id=effective_telephony_id,
        exclude_agent_id=db_agent.id,
    )

    # Convert the update model to dict, handling None values properly
    # Use model_dump with exclude_unset to only get fields that were explicitly provided
    
    # Apply updates
    for field, value in update_data.items():
        setattr(db_agent, field, value)
    
    db.commit()
    db.refresh(db_agent)

    from app.services.telephony.phone_routing import sync_agent_telephony_number_link

    if "telephony_phone_number_id" in update_data or "phone_number" in update_data:
        sync_agent_telephony_number_link(db, db_agent)
        db.refresh(db_agent)

    if "voice_ai_agent_id" in update_data or "voice_ai_integration_id" in update_data:
        integration_id = db_agent.voice_ai_integration_id
        provider_prompt_updated = "provider_prompt" in update_data
        if integration_id and db_agent.voice_ai_agent_id and not provider_prompt_updated:
            try:
                from app.services.voice_providers.prompt_sync import sync_provider_prompt
                integration = db.query(Integration).filter(Integration.id == integration_id).first()
                if integration:
                    sync_provider_prompt(db_agent, integration, db)
                    db.refresh(db_agent)
            except Exception as e:
                logger.warning(f"[Agents] Best-effort provider prompt sync failed on update: {e}")

    return db_agent


@router.post("/{agent_id}/sync-provider-prompt")
async def sync_agent_provider_prompt(
    agent_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Fetch and store the current system prompt from the voice provider."""
    try:
        agent_uuid = UUID(agent_id)
        db_agent = db.query(Agent).filter(
            and_(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        db_agent = db.query(Agent).filter(
            and_(
                Agent.agent_id == agent_id,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()

    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    if not db_agent.voice_ai_integration_id or not db_agent.voice_ai_agent_id:
        raise HTTPException(
            status_code=400,
            detail="Agent is not linked to an external voice provider",
        )

    integration = db.query(Integration).filter(
        and_(
            Integration.id == db_agent.voice_ai_integration_id,
            Integration.organization_id == organization_id,
            Integration.is_active == True,
        )
    ).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found or inactive")

    try:
        from app.services.voice_providers.prompt_sync import sync_provider_prompt
        prompt = sync_provider_prompt(db_agent, integration, db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch prompt from provider: {str(e)}")

    db.refresh(db_agent)
    synced = isinstance(prompt, str) and bool(prompt.strip())
    if not synced:
        raise HTTPException(
            status_code=422,
            detail="Provider returned no prompt. Verify the external agent has a system prompt configured.",
        )
    return {
        "synced": synced,
        "provider_prompt": db_agent.provider_prompt,
        "provider_prompt_synced_at": db_agent.provider_prompt_synced_at.isoformat() if db_agent.provider_prompt_synced_at else None,
    }


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    force: bool = Query(False, description="Force delete with all dependent records"),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Delete an agent (scoped to the active workspace). Returns 409 if dependent records exist unless force=true."""
    try:
        agent_uuid = UUID(agent_id)
        db_agent = db.query(Agent).filter(
            and_(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        db_agent = db.query(Agent).filter(
            and_(
                Agent.agent_id == agent_id,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()
    
    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    agent_uuid = db_agent.id
    dependencies = get_agent_dependencies(db, organization_id, agent_uuid)

    if dependencies and not force:
        parts = []
        if dependencies.get("evaluators"):
            parts.append(f"{dependencies['evaluators']} evaluator(s)")
        if dependencies.get("evaluator_results"):
            parts.append(f"{dependencies['evaluator_results']} evaluator result(s)")
        if dependencies.get("call_recordings"):
            parts.append(f"{dependencies['call_recordings']} call recording(s)")
        if dependencies.get("conversation_evaluations"):
            parts.append(f"{dependencies['conversation_evaluations']} conversation evaluation(s)")
        if dependencies.get("test_conversations"):
            parts.append(f"{dependencies['test_conversations']} test conversation(s)")

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"Cannot delete agent. It is referenced by: {', '.join(parts)}.",
                "dependencies": dependencies,
                "hint": "Use force=true to delete this agent and all its dependent records.",
            },
        )

    if dependencies:
        # Delete in FK-safe order:
        # 1. EvaluatorResults (references evaluators and agents)
        db.query(EvaluatorResult).filter(
            EvaluatorResult.agent_id == agent_uuid,
        ).delete(synchronize_session=False)

        # 2. Evaluators (references agents)
        db.query(Evaluator).filter(
            Evaluator.agent_id == agent_uuid,
        ).delete(synchronize_session=False)

        # 3. Nullify call recordings (keep recordings, unlink agent)
        db.query(CallRecording).filter(
            CallRecording.agent_id == agent_uuid,
        ).update({CallRecording.agent_id: None}, synchronize_session=False)

        # 4. ConversationEvaluations
        db.query(ConversationEvaluation).filter(
            ConversationEvaluation.agent_id == agent_uuid,
        ).delete(synchronize_session=False)

        # 5. TestAgentConversations
        db.query(TestAgentConversation).filter(
            TestAgentConversation.agent_id == agent_uuid,
        ).delete(synchronize_session=False)

    db.delete(db_agent)
    db.commit()

    if dependencies:
        return JSONResponse(
            status_code=200,
            content={
                "message": "Agent and all dependent records deleted successfully.",
                "deleted": dependencies,
            },
        )

    return Response(status_code=204)


@router.get("/{agent_id}/delete-impact")
async def get_agent_delete_impact(
    agent_id: str,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db)
):
    """Preview dependent records that would be affected by force delete (scoped to the active workspace)."""
    try:
        agent_uuid = UUID(agent_id)
        db_agent = db.query(Agent).filter(
            and_(
                Agent.id == agent_uuid,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()
    except ValueError:
        db_agent = db.query(Agent).filter(
            and_(
                Agent.agent_id == agent_id,
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
        ).first()

    if not db_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    dependencies = get_agent_dependencies(db, organization_id, db_agent.id)
    return {
        "agent_id": str(db_agent.id),
        "agent_name": db_agent.name,
        "dependencies": dependencies,
        "can_delete_without_force": len(dependencies) == 0,
    }


from app.core.auth.capabilities import SIM_MANAGE, SIM_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=SIM_VIEW,
    manage_capability=SIM_MANAGE,
)

