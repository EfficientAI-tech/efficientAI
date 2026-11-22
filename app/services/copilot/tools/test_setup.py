"""Generate a test-agent setup draft (test prompt + scenarios). Saves nothing.

The full draft goes to the chat UI as a card the user can review; the model
only gets a short summary, which keeps long prompts out of the conversation
context. Saving drafts (with explicit user confirmation) is a later phase.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.auth.capabilities import SIM_MANAGE
from app.services.copilot.registry import (
    SIDE_EFFECT_GENERATE,
    CopilotTool,
    ToolContext,
    ToolError,
    ToolOutput,
    register,
)
from app.services.copilot.tools.workspace import _enum, _resolve_agent

MAX_PROMPT_CHARS = 30_000


class TestSetupArgs(BaseModel):
    agent: Optional[str] = Field(
        None, max_length=64, description="Existing agent (UUID or 6-digit id) whose production prompt to use."
    )
    production_prompt: Optional[str] = Field(
        None,
        max_length=MAX_PROMPT_CHARS,
        description="The production agent's system prompt, if the user pasted one.",
    )
    agent_name: Optional[str] = Field(None, max_length=255)
    scenario_count: int = Field(5, ge=1, le=10)
    language: Optional[str] = Field(None, max_length=32)
    call_type: Optional[str] = Field(None, description="inbound or outbound", max_length=32)
    additional_context: Optional[str] = Field(
        None, max_length=4_000, description="What the user wants tested, edge cases, tone, etc."
    )

    @model_validator(mode="after")
    def _needs_a_prompt(self):
        if not self.agent and not (self.production_prompt or "").strip():
            raise ValueError("give either `agent` or `production_prompt`")
        return self


def _generate_test_setup(ctx: ToolContext, db: Session, args: TestSetupArgs) -> ToolOutput:
    from app.services.testing.agent_test_setup_generation import (
        generate_scenarios_from_test_prompt,
        generate_test_prompt_from_production,
    )

    if ctx.llm.provider is None:
        raise ToolError("No LLM is configured for this organization, so drafts can't be generated.")
    agent = _resolve_agent(db, ctx, args.agent) if args.agent else None
    prompt = (args.production_prompt or "").strip() or (agent.provider_prompt if agent else "") or ""
    if not prompt.strip():
        raise ToolError("That agent has no production prompt yet. Ask the user to paste it.")
    agent_name = args.agent_name or (agent.name if agent else None) or "Agent"
    call_type = args.call_type or (_enum(agent.call_type) if agent else None)
    language = args.language or (_enum(agent.language) if agent else None)
    llm = ctx.llm
    try:
        prompt_result = generate_test_prompt_from_production(
            prompt,
            agent_name=agent_name,
            language=language,
            call_type=call_type,
            additional_context=args.additional_context,
            llm_provider=llm.provider,
            llm_model=llm.model,
            organization_id=ctx.organization_id,
            db=db,
            credential_id=llm.credential_id,
        )
        scenario_result = generate_scenarios_from_test_prompt(
            prompt_result.test_agent_prompt,
            agent_name=agent_name,
            scenario_count=args.scenario_count,
            language=language,
            call_type=call_type,
            call_medium=_enum(agent.call_medium) if agent else None,
            additional_context=args.additional_context,
            llm_provider=llm.provider,
            llm_model=llm.model,
            organization_id=ctx.organization_id,
            db=db,
            credential_id=llm.credential_id,
        )
    except ValueError as exc:
        raise ToolError(f"Could not generate the setup: {exc}") from exc

    first = prompt_result.first_message
    scenarios = [
        {"name": s.name, "description": s.description, "goal": s.goal}
        for s in scenario_result.scenarios
    ]
    draft = {
        "kind": "test_setup",
        "agent_id": str(agent.id) if agent else None,
        "agent_name": agent_name,
        "sections": [
            {"key": s.key, "title": s.title, "content": s.content} for s in prompt_result.sections
        ],
        "test_agent_prompt": prompt_result.test_agent_prompt,
        "first_message": {
            "production_mode": first.production_mode,
            "production_message": first.production_message,
            "caller_mode": first.caller_mode,
            "caller_message": first.caller_message,
        },
        "scenarios": scenarios,
        "model": scenario_result.model,
        "saved": False,
    }
    return ToolOutput(
        data={
            "status": "draft_ready",
            "saved": False,
            "agent_name": agent_name,
            "test_prompt_sections": [s["title"] for s in draft["sections"]],
            "caller_first_message": first.caller_message,
            "scenarios": [s["name"] for s in scenarios],
            "note": (
                "The full draft is shown to the user as a card. Nothing was saved. "
                "Summarise it briefly and ask what they want to change."
            ),
        },
        ui={"type": "draft", "draft": draft},
    )


register(CopilotTool(
    name="generate_test_setup",
    description=(
        "Draft a test setup for a voice or chat agent: a structured test-agent (simulated caller) "
        "prompt and test scenarios, generated from the production agent's prompt. Use an existing "
        "agent or a prompt the user pasted. Returns a draft only; nothing is saved. Takes ~30s."
    ),
    args_model=TestSetupArgs,
    handler=_generate_test_setup,
    capability=SIM_MANAGE,
    side_effect=SIDE_EFFECT_GENERATE,
    group="setup",
))
