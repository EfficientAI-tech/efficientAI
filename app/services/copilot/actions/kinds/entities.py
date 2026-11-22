"""Create and edit personas, scenarios, metrics and evaluation suites."""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.auth.capabilities import METRICS_MANAGE, SIM_MANAGE
from app.services.copilot.actions.base import (
    ActionContext,
    ActionKind,
    ActionResult,
    EntityRef,
    register_kind,
)
from app.services.copilot.actions.kinds._common import (
    agent_or_error,
    enum_value,
    persona_or_error,
    response_status,
    scenario_or_error,
)

# --- personas -----------------------------------------------------------------

PERSONA_EDITABLE = ("name", "description", "gender", "max_turns", "llm_temperature", "response_delay_ms")


class PersonaFields(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(
        ..., min_length=1, max_length=20_000,
        description="Who the simulated caller is and how they behave (this is the persona prompt).",
    )
    simulation_medium: Optional[Literal["voice", "text"]] = Field(
        None, description="voice for phone/web-call agents, text for chat agents. Omit to infer."
    )
    gender: Optional[Literal["male", "female", "neutral"]] = None
    max_turns: Optional[int] = Field(None, ge=1, le=100)


async def _create_persona(ctx: ActionContext, p: PersonaFields) -> ActionResult:
    from app.api.v1.routes.personas import create_persona
    from app.models.schemas import PersonaCreate

    data: dict[str, Any] = {"name": p.name, "description": p.description}
    if p.simulation_medium:
        data["simulation_medium"] = p.simulation_medium
    if p.gender:
        data["gender"] = p.gender
    if p.max_turns:
        data["max_turns"] = p.max_turns
    persona = await create_persona(
        persona=PersonaCreate(**data),
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
        _principal=None,
    )
    medium = enum_value(persona.simulation_medium)
    return ActionResult(
        summary=f"Created persona '{persona.name}' ({medium or 'voice'}, no voice picked yet; set one on the Personas page).",
        created=[EntityRef("persona", str(persona.id), persona.name, "/personas")],
        undo_state={"persona_id": str(persona.id)},
    )


async def _delete_persona(ctx: ActionContext, state: dict[str, Any]) -> None:
    from app.api.v1.routes.personas import delete_persona

    response = await delete_persona(
        persona_id=UUID(state["persona_id"]),
        force=False,  # never cascade: if something uses it now, undo is refused
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )
    if (response_status(response) or 200) >= 400:
        raise ValueError("The persona is now in use, so it can't be removed automatically.")


class PersonaUpdateFields(BaseModel):
    persona_id: UUID
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, min_length=1, max_length=20_000)
    gender: Optional[Literal["male", "female", "neutral"]] = None
    max_turns: Optional[int] = Field(None, ge=1, le=100)
    llm_temperature: Optional[float] = Field(None, ge=0, le=2)
    response_delay_ms: Optional[int] = Field(None, ge=0, le=10_000)

    @model_validator(mode="after")
    def _has_change(self):
        if not self.changes():
            raise ValueError("nothing to change")
        return self

    def changes(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in PERSONA_EDITABLE if getattr(self, k) is not None}


def _snapshot(row: Any, keys) -> dict[str, Any]:
    return {k: enum_value(getattr(row, k)) for k in keys}


async def _update_persona(ctx: ActionContext, p: PersonaUpdateFields) -> ActionResult:
    from app.api.v1.routes.personas import update_persona
    from app.models.schemas import PersonaUpdate

    current = persona_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, p.persona_id)
    changes = p.changes()
    before = _snapshot(current, changes.keys())
    persona = await update_persona(
        persona_id=p.persona_id,
        persona_update=PersonaUpdate(**changes),
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )
    return ActionResult(
        summary=f"Updated persona '{persona.name}': {', '.join(changes)}.",
        updated=[EntityRef("persona", str(persona.id), persona.name, "/personas")],
        undo_state={"persona_id": str(persona.id), "before": before, "after": _snapshot(persona, changes.keys())},
    )


async def _revert_persona(ctx: ActionContext, state: dict[str, Any]) -> None:
    from app.api.v1.routes.personas import update_persona
    from app.models.schemas import PersonaUpdate

    current = persona_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, UUID(state["persona_id"]))
    if _snapshot(current, state["after"].keys()) != state["after"]:
        raise ValueError("The persona was edited again since, so undo would overwrite those changes.")
    await update_persona(
        persona_id=current.id,
        persona_update=PersonaUpdate(**state["before"]),
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )


register_kind(ActionKind(
    kind="create_persona",
    title="Create persona",
    payload_model=PersonaFields,
    apply=_create_persona,
    undo=_delete_persona,
    describe=lambda p: f"New persona '{p.name}'",
    capability=SIM_MANAGE,
))
register_kind(ActionKind(
    kind="update_persona",
    title="Edit persona",
    payload_model=PersonaUpdateFields,
    apply=_update_persona,
    undo=_revert_persona,
    describe=lambda p: f"Change {', '.join(p.changes())} of a persona",
    capability=SIM_MANAGE,
))

# --- scenarios ------------------------------------------------------------------

SCENARIO_EDITABLE = ("name", "description", "required_info")


class ScenarioFields(BaseModel):
    agent_id: UUID = Field(..., description="The agent this scenario tests.")
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=20_000, description="What the caller wants and how the call should go.")
    required_info: dict[str, str] = Field(
        default_factory=dict, description="Facts the simulated caller can give when asked, e.g. order number."
    )


async def _create_scenario(ctx: ActionContext, p: ScenarioFields) -> ActionResult:
    from app.api.v1.routes.scenarios import create_scenario
    from app.models.schemas import ScenarioCreate

    agent_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, p.agent_id)
    scenario = await create_scenario(
        scenario=ScenarioCreate(
            name=p.name, agent_id=p.agent_id, description=p.description, required_info=p.required_info
        ),
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
        _principal=None,
    )
    return ActionResult(
        summary=f"Created scenario '{scenario.name}'.",
        created=[EntityRef("scenario", str(scenario.id), scenario.name, "/scenarios")],
        undo_state={"scenario_id": str(scenario.id)},
    )


async def _delete_scenario(ctx: ActionContext, state: dict[str, Any]) -> None:
    from app.api.v1.routes.scenarios import delete_scenario

    response = await delete_scenario(
        scenario_id=UUID(state["scenario_id"]),
        force=False,
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )
    if (response_status(response) or 200) >= 400:
        raise ValueError("The scenario is now in use, so it can't be removed automatically.")


class ScenarioUpdateFields(BaseModel):
    scenario_id: UUID
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, min_length=1, max_length=20_000)
    required_info: Optional[dict[str, str]] = None

    @model_validator(mode="after")
    def _has_change(self):
        if not self.changes():
            raise ValueError("nothing to change")
        return self

    def changes(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in SCENARIO_EDITABLE if getattr(self, k) is not None}


async def _update_scenario(ctx: ActionContext, p: ScenarioUpdateFields) -> ActionResult:
    from app.api.v1.routes.scenarios import update_scenario
    from app.models.schemas import ScenarioUpdate

    current = scenario_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, p.scenario_id)
    changes = p.changes()
    before = _snapshot(current, changes.keys())
    scenario = await update_scenario(
        scenario_id=p.scenario_id,
        scenario_update=ScenarioUpdate(**changes),
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )
    return ActionResult(
        summary=f"Updated scenario '{scenario.name}': {', '.join(changes)}.",
        updated=[EntityRef("scenario", str(scenario.id), scenario.name, "/scenarios")],
        undo_state={"scenario_id": str(scenario.id), "before": before, "after": _snapshot(scenario, changes.keys())},
    )


async def _revert_scenario(ctx: ActionContext, state: dict[str, Any]) -> None:
    from app.api.v1.routes.scenarios import update_scenario
    from app.models.schemas import ScenarioUpdate

    current = scenario_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, UUID(state["scenario_id"]))
    if _snapshot(current, state["after"].keys()) != state["after"]:
        raise ValueError("The scenario was edited again since, so undo would overwrite those changes.")
    await update_scenario(
        scenario_id=current.id,
        scenario_update=ScenarioUpdate(**state["before"]),
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )


register_kind(ActionKind(
    kind="create_scenario",
    title="Create scenario",
    payload_model=ScenarioFields,
    apply=_create_scenario,
    undo=_delete_scenario,
    describe=lambda p: f"New scenario '{p.name}'",
    capability=SIM_MANAGE,
))
register_kind(ActionKind(
    kind="update_scenario",
    title="Edit scenario",
    payload_model=ScenarioUpdateFields,
    apply=_update_scenario,
    undo=_revert_scenario,
    describe=lambda p: f"Change {', '.join(p.changes())} of a scenario",
    capability=SIM_MANAGE,
))

# --- metrics --------------------------------------------------------------------


class MetricFields(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(
        ..., min_length=1, max_length=10_000, description="Exactly what the judge should check, in plain words."
    )
    metric_type: Literal["boolean", "rating", "number"] = Field(
        "boolean", description="boolean = pass/fail (best for 'did the agent do X'), rating = 1-5 quality score."
    )
    surfaces: list[Literal["agent", "chat_agent"]] = Field(
        default_factory=lambda: ["agent"], description="agent = voice agents, chat_agent = chat agents."
    )


def _create_metric(ctx: ActionContext, p: MetricFields) -> ActionResult:
    from app.api.v1.routes.metrics import create_metric
    from app.models.schemas import MetricCreate

    result = create_metric(
        metric_data=MetricCreate(
            name=p.name,
            description=p.description,
            metric_type=p.metric_type,
            supported_surfaces=list(p.surfaces),
            scope="workspace",
        ),
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )
    metric_id = str(result["id"] if isinstance(result, dict) else result.id)
    return ActionResult(
        summary=f"Created {p.metric_type} metric '{p.name}'.",
        created=[EntityRef("metric", metric_id, p.name, "/metrics-management")],
        undo_state={"metric_id": metric_id},
    )


def _delete_metric(ctx: ActionContext, state: dict[str, Any]) -> None:
    from app.api.v1.routes.metrics import delete_metric
    from app.models.database import Metric

    metric = ctx.db.query(Metric).filter(
        Metric.id == UUID(state["metric_id"]), Metric.organization_id == ctx.organization_id,
        Metric.workspace_id == ctx.workspace_id,
    ).first()
    if metric is None:
        return
    delete_metric(metric_id=metric.id, organization_id=ctx.organization_id, db=ctx.db)


register_kind(ActionKind(
    kind="create_metric",
    title="Create metric",
    payload_model=MetricFields,
    apply=_create_metric,
    undo=_delete_metric,
    describe=lambda p: f"New {p.metric_type} metric '{p.name}'",
    capability=METRICS_MANAGE,
))

# --- evaluation suites ------------------------------------------------------------


class SuiteFields(BaseModel):
    agent_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    persona_ids: list[UUID] = Field(..., min_length=1)
    scenario_ids: list[UUID] = Field(..., min_length=1, description="Scenarios linked to this agent.")
    metric_ids: Optional[list[UUID]] = Field(None, description="Omit to use the agent's enabled metrics.")
    runs_per_combination: int = Field(1, ge=1, le=10)


def _create_suite(ctx: ActionContext, p: SuiteFields) -> ActionResult:
    from app.api.v1.routes.evaluator_suites import create_suite
    from app.models.schemas import EvaluatorSuiteCreate

    agent_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, p.agent_id)
    suite = create_suite(
        data=EvaluatorSuiteCreate(
            name=p.name,
            agent_id=p.agent_id,
            persona_ids=p.persona_ids,
            scenario_ids=p.scenario_ids,
            metric_ids=p.metric_ids,
            default_runs_per_combination=p.runs_per_combination,
        ),
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )
    suite_id = str(suite["id"] if isinstance(suite, dict) else suite.id)
    combos = len(p.persona_ids) * len(p.scenario_ids)
    return ActionResult(
        summary=f"Created evaluation suite '{p.name}' with {combos} persona × scenario combinations.",
        created=[EntityRef("evaluation suite", suite_id, p.name, f"/evaluate-test-agents/{suite_id}")],
        undo_state={"suite_id": suite_id},
        data={"suite_id": suite_id},
    )


def _delete_suite(ctx: ActionContext, state: dict[str, Any]) -> None:
    from app.api.v1.routes.evaluator_suites import delete_suite

    delete_suite(
        suite_id=UUID(state["suite_id"]),
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        db=ctx.db,
    )


register_kind(ActionKind(
    kind="create_evaluator_suite",
    title="Create evaluation suite",
    payload_model=SuiteFields,
    apply=_create_suite,
    undo=_delete_suite,
    describe=lambda p: f"Suite '{p.name}': {len(p.persona_ids)} persona(s) × {len(p.scenario_ids)} scenario(s)",
    capability=SIM_MANAGE,
))
