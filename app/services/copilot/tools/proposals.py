"""Model-facing tools that propose changes (each confirmed by the user on a card),
plus the hand-off to the create-agent wizard."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth.capabilities import SIM_MANAGE
from app.models.database import CopilotSession
from app.services.copilot.actions.base import get_kind
from app.services.copilot.actions.kinds.setup import PersonaIn
from app.services.copilot.actions.tooling import proposal_tool
from app.services.copilot.registry import CopilotTool, ToolContext, ToolError, ToolOutput, register
from app.services.copilot.tools.workspace import _resolve_agent

# --- test setup from the session's generated draft --------------------------------------


class SaveSetupArgs(BaseModel):
    agent: Optional[str] = Field(None, max_length=64, description="Agent to save onto. Defaults to the draft's agent.")
    include_test_prompt: bool = True
    scenario_names: Optional[list[str]] = Field(
        None, description="Only these drafted scenarios (by name). Omit for all of them."
    )
    personas: list[PersonaIn] = Field(
        default_factory=list, max_length=10,
        description="Personas to create alongside (name + who they are and how they behave).",
    )


def _prepare_setup(ctx: ToolContext, db: Session, args: SaveSetupArgs) -> dict[str, Any]:
    draft = (
        (db.query(CopilotSession.draft).filter(CopilotSession.id == ctx.session_id).scalar() or {})
        .get("test_setup")
    )
    if not draft:
        raise ToolError("There's no generated test setup in this conversation yet. Run generate_test_setup first.")
    agent_ref = args.agent or draft.get("agent_id")
    if not agent_ref:
        raise ToolError("Which agent should this be saved on? The draft came from a pasted prompt.")
    agent = _resolve_agent(db, ctx, agent_ref)
    scenarios = draft.get("scenarios") or []
    if args.scenario_names is not None:
        wanted = {n.strip().lower() for n in args.scenario_names}
        scenarios = [s for s in scenarios if s["name"].strip().lower() in wanted]
    first = draft.get("first_message") or {}
    return {
        "agent_id": str(agent.id),
        "sections": draft.get("sections") if args.include_test_prompt else [],
        "first_message": {k: v for k, v in first.items() if v is not None} if args.include_test_prompt else None,
        "scenarios": [{"name": s["name"], "description": s["description"], "goal": s.get("goal")} for s in scenarios],
        "personas": [p.model_dump() for p in args.personas],
    }


proposal_tool(
    name="propose_save_test_setup",
    kind="save_test_setup",
    description=(
        "Save the test setup drafted by generate_test_setup in this conversation (test-agent prompt and "
        "scenarios), optionally with new personas, onto an agent in one step."
    ),
    args_model=SaveSetupArgs,
    prepare=_prepare_setup,
)

# --- one tool per remaining action kind -----------------------------------------------------

_SIMPLE = [
    ("propose_create_persona", "create_persona", "Create a simulated-caller persona.", "setup"),
    ("propose_update_persona", "update_persona", "Edit an existing persona (only the fields given change).", "setup"),
    ("propose_create_scenario", "create_scenario",
     "Create a test scenario for an agent. Good scenarios come from real calls (see search_import_rows).", "setup"),
    ("propose_update_scenario", "update_scenario", "Edit an existing scenario (only the fields given change).", "setup"),
    ("propose_create_metric", "create_metric",
     "Create an evaluation metric, e.g. to catch a failure pattern found in imported calls.", "setup"),
    ("propose_create_evaluation_suite", "create_evaluator_suite",
     "Create an evaluation suite: an agent tested with every persona × scenario combination.", "setup"),
    ("propose_start_simulation_run", "start_simulation_run",
     "Start a simulation run (simulated calls for scenario × persona combinations, scored by metrics).", "simulations"),
    ("propose_run_evaluation_suite", "run_evaluator_suite", "Run every combination of an evaluation suite.", "simulations"),
    ("propose_analyse_simulation_failures", "analyse_simulation_failures",
     "Cluster a finished simulation run's failures and suggest prompt fixes.", "simulations"),
    ("propose_map_import_columns", "map_import_columns",
     "Map an uploaded import file's columns to an import schema (see get_import_upload).", "imports"),
    ("propose_start_import_evaluation", "start_import_evaluation",
     "Evaluate an import's calls with chosen metrics (uses the calls' own transcripts).", "imports"),
    ("propose_cancel_import_evaluation", "cancel_import_evaluation", "Stop a running import evaluation.", "imports"),
    ("propose_retry_import_evaluation", "retry_import_evaluation", "Retry the failed calls of an import evaluation.", "imports"),
    ("propose_review_prompt_suggestions", "review_prompt_suggestions",
     "Accept or reject prompt suggestions from an import evaluation.", "imports"),
    ("propose_push_prompt_improvements", "push_prompt_improvements",
     "Apply accepted prompt suggestions to the agent's prompt, and optionally its live voice-platform agent.", "imports"),
]

for tool_name, kind, description, group in _SIMPLE:
    proposal_tool(name=tool_name, kind=kind, description=description, group=group)


# --- hand-off to the create-agent wizard -----------------------------------------------------


class WizardArgs(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    call_medium: Literal["voice", "chat"] = "voice"
    production_prompt: Optional[str] = Field(None, max_length=30_000)
    description: Optional[str] = Field(None, max_length=2_000)


def _open_wizard(ctx: ToolContext, db: Session, args: WizardArgs) -> ToolOutput:
    return ToolOutput(
        data={
            "status": "wizard_ready",
            "note": (
                "The user sees an 'Open in agent wizard' button that opens the create-agent form "
                "pre-filled. Connecting telephony or a chat endpoint happens there."
            ),
        },
        ui={"type": "wizard", "wizard": {"kind": "create_agent", **args.model_dump()}},
    )


register(CopilotTool(
    name="open_create_agent_wizard",
    description=(
        "Start creating a new production agent: opens the create-agent wizard pre-filled with a name, "
        "medium and prompt. Use when the user wants a new agent (connections and phone numbers need the wizard)."
    ),
    args_model=WizardArgs,
    handler=_open_wizard,
    capability=SIM_MANAGE,
    group="setup",
    needs_db=False,
))

assert all(get_kind(kind) for _, kind, _, _ in _SIMPLE)
