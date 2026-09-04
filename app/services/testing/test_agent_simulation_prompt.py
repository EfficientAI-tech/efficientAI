"""Build test-agent simulator LLM prompts from agent, scenario, and persona."""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence, TYPE_CHECKING

from app.models.database import Agent, Persona, Scenario
from app.services.testing.test_agent_template import SPOKEN_IDENTITY_GUARDRAIL

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.models.database import Evaluator

SCENARIO_REFERENCE_HEADING = "## Test scenarios (reference)"


def strip_scenario_reference_appendix(markdown: str) -> str:
    """Remove the scenario reference appendix from agent description (not used at eval runtime)."""
    base = (markdown or "").strip()
    if not base:
        return ""
    pattern = re.compile(
        rf"\n?{re.escape(SCENARIO_REFERENCE_HEADING)}[\s\S]*$",
        re.MULTILINE,
    )
    return pattern.sub("", base).rstrip()


def scenario_reference_token(scenario: Scenario) -> str:
    """Stable @scenario{uuid} token for linking scenarios in agent markdown."""
    return f"@scenario{{{scenario.id}}}"


def get_agent_base_prompt(agent: Agent) -> str:
    """Return the core agent prompt text used for simulation composition."""
    description = strip_scenario_reference_appendix(agent.description or "")
    if description:
        return description
    provider = (getattr(agent, "provider_prompt", None) or "").strip()
    if provider:
        return provider
    return "A voice AI assistant"


def _format_required_info(required_info: Any) -> str:
    if not required_info:
        return ""
    if isinstance(required_info, dict):
        lines = []
        for key, value in required_info.items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)
    return str(required_info)


def scenario_goal_from_required_info(scenario: Scenario, default: str = "Complete the test call successfully") -> str:
    if scenario.required_info and isinstance(scenario.required_info, dict):
        goal = scenario.required_info.get("goal")
        if goal:
            return str(goal).strip()
    return default


def format_scenario_prompt(scenario: Scenario) -> str:
    """Format scenario fields for inclusion in test_agent_simulation_prompt."""
    parts: list[str] = []
    name = (scenario.name or "").strip()
    if name:
        parts.append(f"Scenario: {name}")
    description = (getattr(scenario, "description", None) or "").strip()
    if description:
        parts.append(f"Description: {description}")
    goal = scenario_goal_from_required_info(scenario)
    if goal:
        parts.append(f"Goal: {goal}")
    required = _format_required_info(getattr(scenario, "required_info", None))
    if required:
        parts.append(f"Required information:\n{required}")
    return "\n".join(parts) if parts else "General test call scenario"


def append_persona_identity_to_caller_prompt(caller_template: str, persona_name: str) -> str:
    """Append explicit caller identity so the LLM speaks as the selected persona."""
    name = (persona_name or "").strip()
    base = (caller_template or "").strip()
    if not name:
        return base or "Simulate a natural caller for the scenario below."
    identity = (
        f"## Caller identity\n\n"
        f"You are {name}. Introduce yourself as {name} and stay in character as {name} "
        f"for the entire call."
    )
    if not base:
        return identity
    if name.lower() in base.lower():
        return f"{base}\n\n{identity}"
    return f"{base}\n\n{identity}"


def compose_test_agent_simulation_prompt(agent: Agent, scenario: Scenario) -> str:
    """Merge core agent prompt and active scenario into test_agent_simulation_prompt."""
    agent_name = (agent.name or "Voice AI Agent").strip()
    base = get_agent_base_prompt(agent)
    scenario_block = format_scenario_prompt(scenario)
    return (
        f"Agent under test: {agent_name}\n\n"
        f"Agent system prompt:\n{base}\n\n"
        f"Active test scenario:\n{scenario_block}"
    )


def format_persona_block(persona: Persona, persona_description: Optional[str] = None) -> str:
    """Dedicated Persona section for the caller LLM (extensible for future fields)."""
    lines: list[str] = []
    name = (persona.name or "").strip()
    if name:
        lines.append(f"Name: {name}")
    gender = getattr(persona, "gender", None)
    if gender is not None:
        gender_val = gender.value if hasattr(gender, "value") else gender
        lines.append(f"Gender: {gender_val}")
    if getattr(persona, "tts_provider", None):
        lines.append(f"Voice provider: {persona.tts_provider}")
    if getattr(persona, "tts_voice_name", None):
        lines.append(f"Voice: {persona.tts_voice_name}")
    if getattr(persona, "tts_voice_id", None):
        lines.append(f"Voice id: {persona.tts_voice_id}")
    extra = (persona_description or "").strip()
    if extra:
        lines.append(f"Description: {extra}")
    return "\n".join(lines) if lines else "Name: Test Caller"


def build_persona_description_for_bridge(persona: Persona) -> str:
    """Build bridge-style persona description string (traits summary)."""
    stored = (getattr(persona, "description", None) or "").strip()
    if stored:
        return stored
    traits: list[str] = []
    if getattr(persona, "gender", None):
        gender_val = persona.gender.value if hasattr(persona.gender, "value") else persona.gender
        traits.append(f"{gender_val} caller")
    if getattr(persona, "tts_voice_name", None):
        traits.append(f"voice: {persona.tts_voice_name}")
    if getattr(persona, "tts_provider", None):
        traits.append(f"provider: {persona.tts_provider}")
    description = f"A caller named {persona.name}"
    if traits:
        description += " (" + ", ".join(traits) + ")"
    return description


def resolve_persona_max_turns(persona: Persona, default: int = 20) -> int:
    """Effective max turns from persona or default."""
    value = getattr(persona, "max_turns", None)
    if value is not None and int(value) >= 1:
        return int(value)
    return default


def build_test_agent_system_prompt(
    agent: Agent,
    persona: Persona,
    scenario: Scenario,
    *,
    max_turns: Optional[int] = None,
    agent_name: Optional[str] = None,
    persona_description: Optional[str] = None,
) -> str:
    """Full caller LLM system prompt: simulation core + persona + instructions."""
    under_test_name = (agent_name or agent.name or "Voice AI Agent").strip()
    persona_name = (persona.name or "Caller").strip()
    effective_max_turns = max_turns if max_turns is not None else resolve_persona_max_turns(persona)
    simulation = compose_test_agent_simulation_prompt(agent, scenario)
    persona_block = format_persona_block(
        persona,
        persona_description=persona_description or build_persona_description_for_bridge(persona),
    )
    return f"""You are {persona_name}, a real person on a phone call.

{SPOKEN_IDENTITY_GUARDRAIL}

CONTEXT (for your eyes only — do not read aloud)
{simulation}

PERSONA
{persona_block}

INSTRUCTIONS:
1. You are CALLING the voice AI agent described above
2. Stay in character as {persona_name} at all times
3. Follow the scenario and work toward the goal
4. Speak naturally as if on a phone call
5. Keep responses concise (1-3 sentences) for natural conversation flow
6. Ask relevant questions to test the agent's capabilities
7. Respond appropriately to what the agent says
8. If the conversation naturally concludes or you've achieved the goal, say goodbye
9. Respond ONLY with what you would say - no stage directions or descriptions

You are calling: {under_test_name}
After {effective_max_turns} exchanges, wrap up the conversation politely."""


def build_live_test_agent_system_prompt(
    agent: Agent,
    persona: Persona,
    scenario: Scenario,
    *,
    max_turns: Optional[int] = None,
    persona_description: Optional[str] = None,
) -> str:
    """System prompt for live playground calls: caller template + persona + scenario.

    The human plays the production agent; the voice bundle simulates the caller.
    """
    agent_name = (agent.name or "Voice AI Agent").strip()
    persona_name = (persona.name or "Caller").strip()
    effective_max_turns = max_turns if max_turns is not None else resolve_persona_max_turns(persona)
    caller_template = append_persona_identity_to_caller_prompt(
        strip_scenario_reference_appendix(agent.description or "").strip(),
        persona_name,
    )

    production_context = (getattr(agent, "provider_prompt", None) or "").strip()
    persona_block = format_persona_block(
        persona,
        persona_description=persona_description or build_persona_description_for_bridge(persona),
    )
    scenario_block = format_scenario_prompt(scenario)
    if persona_name:
        scenario_block = f"{scenario_block}\n\nPlay this scenario as {persona_name}."

    parts = [
        f"You are {persona_name}, a real person on a phone call.",
        SPOKEN_IDENTITY_GUARDRAIL,
        "",
        "CALLER PROMPT",
        caller_template,
        "",
        "PERSONA",
        persona_block,
        "",
        "SCENARIO",
        scenario_block,
    ]
    if production_context:
        parts.extend(
            [
                "",
                "PRODUCTION AGENT CONTEXT (what you are testing)",
                production_context,
            ]
        )
    parts.extend(
        [
            "",
            "INSTRUCTIONS:",
            f"1. You are {persona_name} — speak only as this person",
            "2. Follow the scenario and work toward the goal",
            "3. Speak naturally as if on a phone call",
            "4. Keep responses concise (1-3 sentences)",
            "5. Respond ONLY with spoken words — no stage directions or markdown",
            f"6. The human on the other end is the production agent ({agent_name})",
            f"7. After about {effective_max_turns} exchanges, wrap up politely.",
        ]
    )
    return "\n".join(parts)


def format_scenarios_reference_appendix(scenarios: Sequence[Scenario]) -> str:
    """Markdown appendix listing linked scenarios using @scenario{uuid} reference tokens."""
    if not scenarios:
        return ""
    lines = [
        SCENARIO_REFERENCE_HEADING,
        "",
        "Linked scenarios use `@scenario{<uuid>}` tokens (insert in prose or list below).",
        "At evaluator run time, the **active scenario** for each test is merged into the simulator prompt separately.",
        "",
    ]
    for scenario in scenarios:
        title = (scenario.name or "Untitled scenario").strip()
        desc = (getattr(scenario, "description", None) or "").strip()
        if len(desc) > 240:
            desc = desc[:237] + "..."
        token = scenario_reference_token(scenario)
        summary = desc if desc else "See scenario library for full text."
        lines.append(f"- {token} — **{title}**: {summary}")
    return "\n".join(lines).rstrip()


def merge_generated_description_with_scenario_appendix(
    base_markdown: str,
    appendix: str,
) -> str:
    """Replace or append the scenario reference section on agent description markdown."""
    base = (base_markdown or "").strip()
    appendix = (appendix or "").strip()
    if not appendix:
        return base
    pattern = re.compile(
        rf"\n?{re.escape(SCENARIO_REFERENCE_HEADING)}[\s\S]*$",
        re.MULTILINE,
    )
    stripped = pattern.sub("", base).rstrip()
    if stripped:
        return f"{stripped}\n\n{appendix}"
    return appendix


def format_scenarios_for_generation_context(scenarios: Sequence[Scenario], max_items: int = 20) -> str:
    """Summarize linked scenarios for LLM input when generating agent descriptions."""
    if not scenarios:
        return ""
    lines = ["Linked test scenarios (reference only):"]
    for scenario in list(scenarios)[:max_items]:
        title = (scenario.name or "Untitled").strip()
        desc = (getattr(scenario, "description", None) or "").strip()
        if len(desc) > 500:
            desc = desc[:497] + "..."
        lines.append(f"- {scenario_reference_token(scenario)} ({title}): {desc or '(no description)'}")
    if len(scenarios) > max_items:
        lines.append(f"... and {len(scenarios) - max_items} more")
    return "\n".join(lines)


def load_linked_scenarios_for_agent(
    db: Session,
    *,
    organization_id,
    workspace_id,
    agent_id,
    limit: int = 20,
) -> list[Scenario]:
    """Scenarios linked to an agent via Scenario.agent_id."""
    return (
        db.query(Scenario)
        .filter(
            Scenario.organization_id == organization_id,
            Scenario.workspace_id == workspace_id,
            Scenario.agent_id == agent_id,
        )
        .order_by(Scenario.name.asc())
        .limit(limit)
        .all()
    )


def build_test_agent_system_prompt_for_evaluator(
    db: Session,
    evaluator: Evaluator,
    *,
    max_turns: Optional[int] = None,
) -> str:
    """Build caller system prompt for an evaluator row (web or phone simulator paths)."""
    agent = db.query(Agent).filter(Agent.id == evaluator.agent_id).first()
    persona = db.query(Persona).filter(Persona.id == evaluator.persona_id).first()
    scenario = db.query(Scenario).filter(Scenario.id == evaluator.scenario_id).first()
    if not agent or not persona or not scenario:
        raise ValueError("Evaluator is missing agent, persona, or scenario")
    effective_max_turns = max_turns if max_turns is not None else resolve_persona_max_turns(persona)
    persona_description = build_persona_description_for_bridge(persona)
    return build_test_agent_system_prompt(
        agent,
        persona,
        scenario,
        max_turns=effective_max_turns,
        persona_description=persona_description,
    )
