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
from app.services.ai.llm_service import llm_service
from app.services.testing.test_agent_template import (
    CANONICAL_SECTION_KEYS,
    CANONICAL_SECTION_TITLES,
    TestAgentFirstMessage,
    TestAgentPromptSection,
    TestAgentTemplate,
    assemble_test_agent_prompt,
    derive_caller_first_message,
    normalize_first_message,
    normalize_sections,
    template_from_generation,
)

SCENARIO_DESCRIPTION_SECTIONS: tuple[str, ...] = (
    "### Background (2-3 sentences)",
    "### Caller Intent (1-2 sentences)",
    "### Conversation Flow (4-6 numbered steps)",
    "### Success Criteria (2-4 bullet points)",
    "### Edge Cases to Probe (2-3 bullet points)",
)

GENERATE_TEST_PROMPT_SYSTEM = (
    "You are an expert at generating synthetic voice AI test agents.\n\n"
    "You will receive the system prompt of a production voice AI agent (the assistant that answers calls).\n\n"
    "Your task is to generate the foundational configuration for the complementary test caller "
    "that will call this production agent during evaluation.\n\n"
    "Do NOT generate a specific persona or scenario. Those are supplied separately.\n\n"
    "Return ONLY valid JSON with this exact shape:\n"
    "{\n"
    '  "sections": [\n'
    '    {"key": "complementary_goal", "title": "Role and Goal", "content": "..."},\n'
    '    {"key": "talking_style", "title": "Talking Style", "content": "..."},\n'
    '    {"key": "questions_to_ask", "title": "Questions to Ask", "content": "..."},\n'
    '    {"key": "information_to_relay", "title": "Information to Relay", "content": "..."},\n'
    '    {"key": "constraints", "title": "Constraints", "content": "..."}\n'
    "  ],\n"
    '  "first_message": {\n'
    '    "production_mode": "assistant_speaks_first" | "assistant_waits_for_user" | '
    '"assistant_speaks_first_model_generated",\n'
    '    "production_message": "static greeting text or null"\n'
    "  }\n"
    "}\n\n"
    "Section guidance:\n"
    "- complementary_goal: what the caller should ultimately achieve, inverted from the production agent's goals/criteria\n"
    "- talking_style: how callers of this production agent typically speak (pacing, tone, phone realism)\n"
    "- questions_to_ask: typical questions this caller type would ask the production agent\n"
    "- information_to_relay: facts/details the caller should be ready to provide when asked\n"
    "- constraints: boundaries (don't dump everything at once, don't mention testing/QA, stay realistic)\n\n"
    "First message guidance:\n"
    "- Infer who speaks first on the production side from greeting/opening instructions in the production prompt\n"
    "- production_message: include the static greeting when production_mode is assistant_speaks_first, else null\n"
    "- Do not include caller opening lines in sections; caller behavior is derived from production_mode\n\n"
    "Rules:\n"
    "- Avoid mentioning testing, QA, automation, prompts, or evaluation in section content\n"
    "- Assume persona-specific details and scenario context will be injected later\n"
    "- Leave placeholders where appropriate for persona and scenario\n"
    "- The template must be reusable across many personas and scenarios\n"
    "- Return only JSON, no markdown wrapper, no explanation"
)

GENERATE_SCENARIOS_SYSTEM = (
    "You generate high-quality test scenarios for voice AI agents. "
    "Return ONLY valid JSON array with objects: "
    '{ "name": string, "description": string, "goal": string }.'
)


# Re-export for backward compatibility in tests/imports
AgentTestPromptSection = TestAgentPromptSection


@dataclass
class TestPromptGenerationResult:
    sections: List[TestAgentPromptSection]
    test_agent_prompt: str
    first_message: TestAgentFirstMessage
    test_agent_template: TestAgentTemplate
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


def _strip_llm_text_wrapper(text: str) -> str:
    """Strip optional markdown fences and trim LLM preamble from plain-text responses."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:markdown|md|text|json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


def _extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = _strip_llm_text_wrapper(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(cleaned[start : end + 1])


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


def build_test_prompt_user_message(
    *,
    production_prompt: str,
    agent_name: str,
    language: Optional[str] = None,
    call_type: Optional[str] = None,
    additional_context: Optional[str] = None,
) -> str:
    parts = [
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


def _parse_generation_payload(text: str) -> tuple[List[TestAgentPromptSection], TestAgentFirstMessage]:
    try:
        payload = _extract_json_object(text)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning(f"[AgentTestSetup] Failed to parse test prompt JSON: {exc}")
        raise ValueError("Could not parse generated test agent template from LLM response") from exc

    sections = normalize_sections(payload.get("sections"))
    first_message_raw = payload.get("first_message")
    if isinstance(first_message_raw, dict):
        production_mode = str(first_message_raw.get("production_mode") or "").strip()
        production_message = first_message_raw.get("production_message")
        production_message_str = str(production_message).strip() if production_message else None
        first_message = derive_caller_first_message(production_mode, production_message_str)
    else:
        first_message = normalize_first_message(first_message_raw)

    return sections, first_message


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
    """Stage 1: generate foundational test agent template from production prompt."""
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

    sections, first_message = _parse_generation_payload(result["text"])
    test_agent_prompt = assemble_test_agent_prompt(sections)
    if not test_agent_prompt.strip():
        raise ValueError("LLM response did not contain a test agent prompt")

    template = template_from_generation(sections, first_message)

    return TestPromptGenerationResult(
        sections=sections,
        test_agent_prompt=test_agent_prompt,
        first_message=first_message,
        test_agent_template=template,
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
