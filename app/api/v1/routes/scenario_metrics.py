"""Enterprise scenario-to-metric generation routes."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_api_key,
    get_organization_id,
    get_workspace_id,
    require_enterprise_feature,
)
from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request
from app.services.billing.flexprice_service import record_metrics_llm_assist
from app.services.testing.scenario_metric_generation import (
    ScenarioMetricInput,
    generate_metrics_from_scenarios,
)
from app.services.usage.context import (
    LLMUsageContext,
    LLMUsageProductSection,
    llm_usage_context,
)

router = APIRouter(
    prefix="/metrics",
    tags=["metrics"],
    dependencies=[Depends(require_enterprise_feature("scenario_metrics"))],
)


class ScenarioMetricScenarioInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    goal: Optional[str] = None


class GenerateMetricsFromScenariosRequest(BaseModel):
    agent_name: str = Field(..., min_length=1, max_length=255)
    production_prompt: str = Field(..., min_length=1)
    call_medium: Optional[str] = None
    scenarios: List[ScenarioMetricScenarioInput] = Field(..., min_length=1, max_length=10)
    provider: Optional[str] = None
    model: Optional[str] = None
    credential_id: Optional[UUID] = None
    llm_config: Optional[Dict[str, Any]] = None


class GeneratedScenarioMetricDraftResponse(BaseModel):
    name: str
    description: str
    metric_type: Literal["rating", "boolean", "number", "text"]
    custom_data_type: Optional[Literal["boolean", "enum", "number_range"]] = None
    custom_config: Dict[str, Any] = {}
    supported_surfaces: List[str]
    enabled_surfaces: List[str]
    tags: List[str] = []
    scenario_name: str


class GenerateMetricsFromScenariosResponse(BaseModel):
    metrics: List[GeneratedScenarioMetricDraftResponse]
    provider: str
    model: str


@router.post("/generate-from-scenarios", response_model=GenerateMetricsFromScenariosResponse)
async def generate_metrics_from_scenarios_route(
    data: GenerateMetricsFromScenariosRequest,
    background_tasks: BackgroundTasks,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Suggest one evaluation metric per scenario; does not persist metrics."""
    provider_enum, model_str = get_llm_provider_and_model_for_request(
        organization_id, db, data.provider, data.model, data.credential_id
    )

    scenario_inputs = [
        ScenarioMetricInput(
            name=item.name.strip(),
            description=item.description.strip(),
            goal=item.goal.strip() if item.goal else None,
        )
        for item in data.scenarios
    ]

    try:
        with llm_usage_context(
            LLMUsageContext(
                organization_id=organization_id,
                workspace_id=workspace_id,
                product_section=LLMUsageProductSection.METRICS,
            )
        ):
            result = generate_metrics_from_scenarios(
                agent_name=data.agent_name.strip(),
                production_prompt=data.production_prompt,
                call_medium=data.call_medium,
                scenarios=scenario_inputs,
                organization_id=organization_id,
                workspace_id=workspace_id,
                db=db,
                llm_provider=provider_enum,
                llm_model=model_str,
                llm_config=data.llm_config,
                credential_id=data.credential_id,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {exc}") from exc

    background_tasks.add_task(
        record_metrics_llm_assist,
        organization_id,
        uuid4(),
        workspace_id=workspace_id,
        mode="scenario_metrics",
    )

    return GenerateMetricsFromScenariosResponse(
        metrics=[
            GeneratedScenarioMetricDraftResponse(
                name=m.name,
                description=m.description,
                metric_type=m.metric_type,  # type: ignore[arg-type]
                custom_data_type=m.custom_data_type,  # type: ignore[arg-type]
                custom_config=m.custom_config,
                supported_surfaces=m.supported_surfaces,
                enabled_surfaces=m.enabled_surfaces,
                tags=m.tags,
                scenario_name=m.scenario_name,
            )
            for m in result.metrics
        ],
        provider=result.provider,
        model=result.model,
    )
