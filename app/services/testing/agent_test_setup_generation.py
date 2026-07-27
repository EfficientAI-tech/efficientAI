"""Generate sectioned test agent prompts and scenarios from production prompts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.enums import ModelProvider
from app.services.agent_flowchart import _extract_json_object
from app.services.ai.llm_service import llm_service

CANONICAL_SECTION_KEYS: tuple[str, ...] = (
    "purpose",
    "behavior",
    "expected_interactions",
    "personality_traits",
    "constraints",
)

CANONICAL_SECTION_TITLES: dict[str, str] = {
    "purpose": "Purpose",
    "behavior": "Behavior",
    "expected_interactions": "Expected Interactions",
    "personality_traits": "Personality Traits",
    "constraints": "Constraints",
}

SCENARIO_DESCRIPTION_SECTIONS: tuple[str, ...] = (
    "### Background (2-3 sentences)",
    "### Caller Intent (1-2 sentences)",
    "### Conversation Flow (4-6 numbered steps)",
    "### Success Criteria (2-4 bullet points)",
    "### Edge Cases to Probe (2-3 bullet points)",
)

GENERATE_TEST_PROMPT_SYSTEM = (
    "You are an expert at mapping production voice AI agent system prompts into "
    "structured test agent prompts for QA evaluation.\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "sections": [\n'
    '    {"key": "purpose", "title": "Purpose", "content": "markdown body only"},\n'
    '    {"key": "behavior", "title": "Behavior", "content": "..."},\n'
    '    {"key": "expected_interactions", "title": "Expected Interactions", "content": "..."},\n'
    '    {"key": "personality_traits", "title": "Personality Traits", "content": "..."},\n'
    '    {"key": "constraints", "title": "Constraints", "content": "..."}\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Map content from the production prompt; do not invent capabilities not implied by the source.\n"
    "- Preserve tools, policies, escalation paths, and tone faithfully within the appropriate section.\n"
    "- If a section has no clear source content, use: \"Not specified in source prompt.\"\n"
    "- Section content must be markdown body only (no ## heading in content).\n"
    "- Suggest {variable} placeholders only where the production prompt clearly has dynamic slots.\n"
    "- Return exactly five sections with the keys shown above.\n"
    "- No markdown wrapper, no preamble."
)

GENERATE_SCENARIOS_SYSTEM = (
    "You generate high-quality test scenarios for voice AI agents. "
    "Return ONLY valid JSON array with objects: "
    '{ "name": string, "description": string, "goal": string }.'
)


@dataclass
class AgentTestPromptSection:
    key: str
    title: str
    content: str


@dataclass
class TestPromptGenerationResult:
    sections: List[AgentTestPromptSection]
    test_agent_prompt: str
    provider: str
    model: str


@dataclass
class ScenarioDraft:
    name: str
    description: str
    goal: Optional[str] = None


@dataclass
class ScenarioGenerationResult:
    scenarios: List[ScenarioDraft]
    provider: str
    model: str


def _extract_json_array(text: str) -> List[Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not contain a JSON array")
    return json.loads(cleaned[start : end + 1])


def assemble_test_agent_prompt(sections: Sequence[AgentTestPromptSection]) -> str:
    """Deterministically assemble canonical sections into markdown."""
    by_key = {section.key: section for section in sections}
    ordered: list[AgentTestPromptSection] = []
    for key in CANONICAL_SECTION_KEYS:
        section = by_key.get(key)
        if section is None:
            ordered.append(
                AgentTestPromptSection(
                    key=key,
                    title=CANONICAL_SECTION_TITLES[key],
                    content="Not specified in source prompt.",
                )
            )
        else:
            ordered.append(section)

    parts: list[str] = []
    for section in ordered:
        title = section.title.strip() or CANONICAL_SECTION_TITLES.get(section.key, section.key)
        content = (section.content or "").strip() or "Not specified in source prompt."
        parts.append(f"## {title}\n\n{content}")
    return "\n\n".join(parts)


def _normalize_sections(raw_sections: Any) -> List[AgentTestPromptSection]:
    if not isinstance(raw_sections, list):
        raise ValueError("LLM response sections must be a list")

    by_key: dict[str, AgentTestPromptSection] = {}
    for item in raw_sections:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key not in CANONICAL_SECTION_KEYS:
            continue
        title = str(item.get("title") or CANONICAL_SECTION_TITLES[key]).strip()
        content = str(item.get("content") or "").strip()
        by_key[key] = AgentTestPromptSection(key=key, title=title, content=content)

    sections: list[AgentTestPromptSection] = []
    for key in CANONICAL_SECTION_KEYS:
        if key in by_key:
            sections.append(by_key[key])
        else:
            sections.append(
                AgentTestPromptSection(
                    key=key,
                    title=CANONICAL_SECTION_TITLES[key],
                    content="Not specified in source prompt.",
                )
            )
    return sections


def _normalize_scenario_drafts(raw: Any) -> List[ScenarioDraft]:
    if not isinstance(raw, list):
        raise ValueError("LLM response scenarios must be a list")

    drafts: list[ScenarioDraft] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        description = str(item.get("description") or "").strip()
        if not name or not description:
            continue
        goal = item.get("goal")
        goal_str = str(goal).strip() if goal else None
        drafts.append(ScenarioDraft(name=name, description=description, goal=goal_str or None))
    if not drafts:
        raise ValueError("LLM response did not contain valid scenario drafts")
    return drafts


def build_test_prompt_user_message(
    *,
    production_prompt: str,
    agent_name: str,
    language: Optional[str] = None,
    call_type: Optional[str] = None,
    additional_context: Optional[str] = None,
) -> str:
    parts = [
        "Map the following production agent system prompt into the five canonical test agent prompt sections.",
        f"Agent Name: {agent_name}",
    ]
    if language:
        parts.append(f"Language: {language}")
    if call_type:
        parts.append(f"Call Type: {call_type}")
    parts.extend(["", f"Production System Prompt:\n{production_prompt.strip()}"])
    if additional_context and additional_context.strip():
        parts.extend(["", f"Additional Context:\n{additional_context.strip()}"])
    return "\n".join(parts)


def build_scenario_generation_requirements() -> str:
    lines = [
        "Requirements:",
        "- Each scenario must test a different user intent or edge case.",
        "- Keep each name short (under 80 characters).",
        "- Each description must be 150-300 words.",
        "- Each description MUST include all of these markdown sections:",
    ]
    lines.extend(f"  - {section}" for section in SCENARIO_DESCRIPTION_SECTIONS)
    lines.extend(
        [
            "- Descriptions should be specific, test-oriented, and suitable for QA evaluation.",
            "- Include a concise goal string summarizing what the caller should achieve.",
            "- Return only JSON array, no markdown wrapper, no explanation.",
        ]
    )
    return "\n".join(lines)


def build_scenario_generation_user_message(
    *,
    test_agent_prompt: str,
    agent_name: str,
    scenario_count: int,
    language: Optional[str] = None,
    call_type: Optional[str] = None,
    additional_context: Optional[str] = None,
) -> str:
    parts = [
        f"Generate {scenario_count} diverse test scenarios from this test agent system prompt.",
        f"Agent Name: {agent_name}",
    ]
    if language:
        parts.append(f"Language: {language}")
    if call_type:
        parts.append(f"Call Type: {call_type}")
    parts.extend(["", f"Test Agent System Prompt:\n{test_agent_prompt.strip()}"])
    if additional_context and additional_context.strip():
        parts.extend(["", f"Additional Generation Context:\n{additional_context.strip()}"])
    parts.extend(["", build_scenario_generation_requirements()])
    return "\n".join(parts)


def generate_test_prompt_from_production(
    production_prompt: str,
    *,
    agent_name: str,
    language: Optional[str],
    call_type: Optional[str],
    additional_context: Optional[str],
    llm_provider: ModelProvider,
    llm_model: str,
    organization_id: UUID,
    db: Session,
    llm_config: Optional[Dict[str, Any]] = None,
    credential_id: Optional[UUID] = None,
) -> TestPromptGenerationResult:
    """Stage 1: map production prompt into canonical test agent prompt sections."""
    if not production_prompt.strip():
        raise ValueError("Production prompt is required")

    messages = [
        {"role": "system", "content": GENERATE_TEST_PROMPT_SYSTEM},
        {
            "role": "user",
            "content": build_test_prompt_user_message(
                production_prompt=production_prompt,
                agent_name=agent_name,
                language=language,
                call_type=call_type,
                additional_context=additional_context,
            ),
        },
    ]

    result = llm_service.generate_response(
        messages=messages,
        llm_provider=llm_provider,
        llm_model=llm_model,
        organization_id=organization_id,
        db=db,
        llm_config=llm_config,
        task_defaults={"temperature": 0.4, "max_tokens": 6000},
        credential_id=credential_id,
    )

    raw = _extract_json_object(result["text"])
    sections = _normalize_sections(raw.get("sections"))
    test_agent_prompt = assemble_test_agent_prompt(sections)

    return TestPromptGenerationResult(
        sections=sections,
        test_agent_prompt=test_agent_prompt,
        provider=llm_provider.value,
        model=llm_model,
    )


def generate_scenarios_from_test_prompt(
    test_agent_prompt: str,
    *,
    agent_name: str,
    scenario_count: int,
    language: Optional[str],
    call_type: Optional[str],
    additional_context: Optional[str],
    llm_provider: ModelProvider,
    llm_model: str,
    organization_id: UUID,
    db: Session,
    llm_config: Optional[Dict[str, Any]] = None,
    credential_id: Optional[UUID] = None,
) -> ScenarioGenerationResult:
    """Stage 2: generate scenario drafts from assembled test agent prompt."""
    if not test_agent_prompt.strip():
        raise ValueError("Test agent prompt is required")
    if scenario_count < 1 or scenario_count > 10:
        raise ValueError("Scenario count must be between 1 and 10")

    messages = [
        {"role": "system", "content": GENERATE_SCENARIOS_SYSTEM},
        {
            "role": "user",
            "content": build_scenario_generation_user_message(
                test_agent_prompt=test_agent_prompt,
                agent_name=agent_name,
                scenario_count=scenario_count,
                language=language,
                call_type=call_type,
                additional_context=additional_context,
            ),
        },
    ]

    result = llm_service.generate_response(
        messages=messages,
        llm_provider=llm_provider,
        llm_model=llm_model,
        organization_id=organization_id,
        db=db,
        llm_config=llm_config,
        task_defaults={"temperature": 0.7, "max_tokens": 8000},
        credential_id=credential_id,
    )

    try:
        raw = _extract_json_array(result["text"])
    except ValueError as exc:
        logger.warning(f"[AgentTestSetup] Failed to parse scenario JSON array: {exc}")
        raise ValueError("Could not parse generated scenarios from LLM response") from exc

    scenarios = _normalize_scenario_drafts(raw)
    return ScenarioGenerationResult(
        scenarios=scenarios,
        provider=llm_provider.value,
        model=llm_model,
    )
