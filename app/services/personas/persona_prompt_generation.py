"""Generate persona caller prompts from agent prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent
from app.models.enums import ModelProvider
from app.services.ai.llm_service import llm_service

SCENARIO_REFERENCE_HEADING = "## Test scenarios (reference)"


def strip_scenario_reference_appendix(markdown: str) -> str:
    if not markdown:
        return ""
    return re.sub(
        rf"\n?{re.escape(SCENARIO_REFERENCE_HEADING)}[\s\S]*$",
        "",
        markdown.strip(),
    ).strip()

GENERATE_PERSONA_PROMPT_SYSTEM = (
    "You are an expert at writing persona prompts for synthetic voice test callers.\n\n"
    "A persona prompt describes how the simulated caller speaks and behaves during phone "
    "conversations. It is appended to the caller LLM system prompt during evaluation runs.\n\n"
    "Guidelines:\n"
    "- Write 2-5 concise sentences in plain prose (not markdown headings).\n"
    "- Describe personality, tone, speaking style, patience, and typical caller behavior.\n"
    "- The caller is testing a voice AI agent — stay in character as a realistic customer/caller.\n"
    "- Do NOT mention testing, QA, automation, LLM, or system prompts.\n"
    "- Do NOT repeat the agent's full system prompt verbatim.\n"
    "- Infer a complementary caller profile from the agent under test.\n"
    "- Return ONLY the persona prompt text."
)


@dataclass
class PersonaPromptGenerationResult:
    persona_prompt: str
    source_used: str
    provider: str
    model: str


def resolve_test_agent_prompt_text(agent: Agent) -> str:
    return strip_scenario_reference_appendix(agent.description or "")


def resolve_agent_production_prompt_text(agent: Agent) -> str:
    return (getattr(agent, "provider_prompt", None) or "").strip()


def resolve_agent_prompt_sources(agent: Agent) -> dict[str, str]:
    """Return available prompt texts for persona seeding."""
    return {
        "test_agent_prompt": resolve_test_agent_prompt_text(agent),
        "agent_prompt": resolve_agent_production_prompt_text(agent),
    }


def _strip_llm_text_wrapper(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:markdown|md|text)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


def build_persona_prompt_user_message(
    *,
    agent: Agent,
    source_prompt: str,
    source_label: str,
    persona_name: Optional[str] = None,
    persona_gender: Optional[str] = None,
    additional_context: Optional[str] = None,
) -> str:
    parts = [
        f"Agent under test: {agent.name}",
        f"Source ({source_label}):",
        source_prompt.strip(),
    ]
    if persona_name:
        parts.append(f"Persona name: {persona_name}")
    if persona_gender:
        parts.append(f"Persona gender: {persona_gender}")
    if additional_context and additional_context.strip():
        parts.append(f"Additional context:\n{additional_context.strip()}")
    parts.append(
        "\nGenerate a persona prompt for the synthetic caller who will interact with this agent."
    )
    return "\n".join(parts)


def generate_persona_prompt_from_agent(
    agent: Agent,
    *,
    source: str,
    persona_name: Optional[str],
    persona_gender: Optional[str],
    additional_context: Optional[str],
    llm_provider: ModelProvider,
    llm_model: str,
    organization_id: UUID,
    db: Session,
    llm_config: Optional[Dict[str, Any]] = None,
    credential_id: Optional[UUID] = None,
) -> PersonaPromptGenerationResult:
    """Generate persona caller prompt text from an agent prompt via LLM."""
    sources = resolve_agent_prompt_sources(agent)
    test_agent_prompt = sources["test_agent_prompt"]
    agent_prompt = sources["agent_prompt"]

    if source == "test_agent":
        source_prompt = test_agent_prompt
        source_label = "test agent prompt"
        if not source_prompt.strip():
            raise ValueError("Selected agent has no test agent prompt to generate from")
    elif source == "agent":
        source_prompt = agent_prompt or test_agent_prompt
        source_label = "agent / production prompt"
        if not source_prompt.strip():
            raise ValueError(
                "Selected agent has no production prompt or test agent prompt to generate from"
            )
    else:
        source_prompt = test_agent_prompt or agent_prompt
        source_label = "agent prompt"
        if not source_prompt.strip():
            raise ValueError(
                "Selected agent has no test agent prompt or production prompt to generate from"
            )

    messages = [
        {"role": "system", "content": GENERATE_PERSONA_PROMPT_SYSTEM},
        {
            "role": "user",
            "content": build_persona_prompt_user_message(
                agent=agent,
                source_prompt=source_prompt,
                source_label=source_label,
                persona_name=persona_name,
                persona_gender=persona_gender,
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
        task_defaults={"temperature": 0.5, "max_tokens": 800},
        credential_id=credential_id,
    )

    persona_prompt = _strip_llm_text_wrapper(result["text"])
    if not persona_prompt:
        raise ValueError("LLM response did not contain a persona prompt")

    return PersonaPromptGenerationResult(
        persona_prompt=persona_prompt,
        source_used=source_label,
        provider=llm_provider.value,
        model=llm_model,
    )
