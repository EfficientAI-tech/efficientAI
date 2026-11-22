"""Save a generated test setup in one step: the agent's test-agent template plus
its scenarios and personas, in a single transaction (all or nothing)."""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.core.auth.capabilities import SIM_MANAGE
from app.models.database import Evaluator, EvaluatorResult, Persona, Scenario
from app.services.copilot.actions.base import (
    ActionContext,
    ActionKind,
    ActionResult,
    EntityRef,
    register_kind,
)
from app.services.copilot.actions.kinds._common import agent_or_error


class SectionIn(BaseModel):
    key: Literal["complementary_goal", "talking_style", "questions_to_ask", "information_to_relay", "constraints"]
    title: str = Field(..., max_length=200)
    content: str = Field(..., max_length=20_000)


class FirstMessageIn(BaseModel):
    production_mode: Literal[
        "assistant_speaks_first", "assistant_waits_for_user", "assistant_speaks_first_model_generated"
    ] = "assistant_waits_for_user"
    production_message: Optional[str] = Field(None, max_length=2_000)
    caller_mode: Literal["wait", "speak_first"] = "speak_first"
    caller_message: Optional[str] = Field(None, max_length=2_000)


class ScenarioIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=20_000)
    goal: Optional[str] = Field(None, max_length=2_000)


class PersonaIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=20_000)


class TestSetupBundle(BaseModel):
    agent_id: UUID
    sections: list[SectionIn] = Field(default_factory=list, max_length=5)
    first_message: Optional[FirstMessageIn] = None
    scenarios: list[ScenarioIn] = Field(default_factory=list, max_length=20)
    personas: list[PersonaIn] = Field(default_factory=list, max_length=10)


def _describe(p: TestSetupBundle) -> str:
    parts = []
    if p.sections:
        parts.append("test-agent prompt")
    if p.scenarios:
        parts.append(f"{len(p.scenarios)} scenario(s)")
    if p.personas:
        parts.append(f"{len(p.personas)} persona(s)")
    return "Save " + (", ".join(parts) or "nothing")


def _apply_bundle(ctx: ActionContext, p: TestSetupBundle) -> ActionResult:
    from app.api.v1.routes.agents import _apply_test_agent_template_fields
    from app.models.schemas import TestAgentTemplateInput
    from app.services.personas.persona_simulation_medium import expected_persona_medium_for_agent

    if not (p.sections or p.scenarios or p.personas):
        raise ValueError("The setup is empty.")
    db = ctx.db
    agent = agent_or_error(db, ctx.organization_id, ctx.workspace_id, p.agent_id)
    undo: dict[str, Any] = {"agent_id": str(agent.id), "scenario_ids": [], "persona_ids": []}
    result = ActionResult(summary="", undo_state=undo)

    if p.sections:
        template_input = TestAgentTemplateInput.model_validate({
            "sections": [s.model_dump() for s in p.sections],
            "first_message": (p.first_message or FirstMessageIn()).model_dump(),
        })
        undo["before_template"] = agent.test_agent_template
        undo["before_description"] = agent.description
        description, template = _apply_test_agent_template_fields(
            description=agent.description, template_input=template_input
        )
        agent.test_agent_template = template
        agent.description = description
        undo["after_template"] = template
        result.updated.append(EntityRef("agent", str(agent.id), agent.name, f"/agents/{agent.id}"))

    for s in p.scenarios:
        scenario = Scenario(
            id=uuid4(),
            organization_id=ctx.organization_id,
            workspace_id=ctx.workspace_id,
            agent_id=agent.id,
            name=s.name,
            description=s.description + (f"\n\nGoal: {s.goal}" if s.goal else ""),
            required_info={},
        )
        db.add(scenario)
        undo["scenario_ids"].append(str(scenario.id))
        result.created.append(EntityRef("scenario", str(scenario.id), s.name, "/scenarios"))

    if p.personas:
        medium = expected_persona_medium_for_agent(agent)
        existing = {
            name for (name,) in db.query(Persona.name).filter(
                Persona.workspace_id == ctx.workspace_id,
                Persona.name.in_([x.name for x in p.personas]),
            )
        }
        for x in p.personas:
            if x.name in existing:
                continue  # reuse the existing persona of that name rather than fail
            persona = Persona(
                id=uuid4(),
                organization_id=ctx.organization_id,
                workspace_id=ctx.workspace_id,
                name=x.name,
                description=x.description,
                simulation_medium=medium,
            )
            db.add(persona)
            undo["persona_ids"].append(str(persona.id))
            result.created.append(EntityRef("persona", str(persona.id), x.name, "/personas"))

    db.commit()  # one transaction: template, scenarios and personas together
    result.summary = (
        f"Saved for agent '{agent.name}': "
        + ", ".join(
            filter(None, [
                "test-agent prompt" if p.sections else "",
                f"{len(undo['scenario_ids'])} scenario(s)" if undo["scenario_ids"] else "",
                f"{len(undo['persona_ids'])} new persona(s)" if undo["persona_ids"] else "",
            ])
        )
        + "."
    )
    result.data = {"scenario_ids": undo["scenario_ids"], "persona_ids": undo["persona_ids"]}
    return result


def _undo_bundle(ctx: ActionContext, state: dict[str, Any]) -> None:
    db = ctx.db
    scenario_ids = [UUID(x) for x in state.get("scenario_ids", [])]
    persona_ids = [UUID(x) for x in state.get("persona_ids", [])]
    in_use = db.query(Evaluator.id).filter(
        (Evaluator.scenario_id.in_(scenario_ids)) | (Evaluator.persona_id.in_(persona_ids))
    ).first() or db.query(EvaluatorResult.id).filter(
        (EvaluatorResult.scenario_id.in_(scenario_ids)) | (EvaluatorResult.persona_id.in_(persona_ids))
    ).first()
    if in_use:
        raise ValueError("Some of these scenarios or personas are already used in tests, so undo would lose data.")
    agent = agent_or_error(db, ctx.organization_id, ctx.workspace_id, UUID(state["agent_id"]))
    if "after_template" in state:
        if agent.test_agent_template != state["after_template"]:
            raise ValueError("The agent's test-agent prompt was edited again since, so undo would overwrite it.")
        agent.test_agent_template = state.get("before_template")
        agent.description = state.get("before_description")
    if scenario_ids:
        db.query(Scenario).filter(
            Scenario.id.in_(scenario_ids), Scenario.workspace_id == ctx.workspace_id
        ).delete(synchronize_session=False)
    if persona_ids:
        db.query(Persona).filter(
            Persona.id.in_(persona_ids), Persona.workspace_id == ctx.workspace_id
        ).delete(synchronize_session=False)
    db.commit()


register_kind(ActionKind(
    kind="save_test_setup",
    title="Save test setup",
    payload_model=TestSetupBundle,
    apply=_apply_bundle,
    undo=_undo_bundle,
    describe=_describe,
    capability=SIM_MANAGE,
))
