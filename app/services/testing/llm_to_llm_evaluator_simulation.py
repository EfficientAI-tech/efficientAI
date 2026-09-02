"""Text-based LLM-to-LLM simulation for evaluator runs without an external voice provider."""

from __future__ import annotations

import re
from typing import Any, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import Agent, Evaluator, EvaluatorResult, Persona, Scenario, VoiceBundle
from app.models.enums import ModelProvider
from app.services.ai.llm_service import llm_service
from app.services.testing.test_agent_simulation_prompt import (
    build_persona_description_for_bridge,
    build_test_agent_system_prompt,
    get_agent_base_prompt,
    resolve_persona_max_turns,
)
from app.services.usage.context import (
    LLMUsageContext,
    LLMUsageProductSection,
    llm_usage_context,
    usage_context_for_test_agent_simulation,
)

_GOODBYE_RE = re.compile(
    r"\b(goodbye|bye|thanks?\s+you|talk\s+to\s+you\s+later|have\s+a\s+(?:good|great)\s+(?:day|one))\b",
    re.IGNORECASE,
)


def _build_agent_system_prompt(agent: Agent) -> str:
    agent_name = (agent.name or "Voice AI Agent").strip()
    base = get_agent_base_prompt(agent)
    return (
        f"You are {agent_name}, a voice AI agent on a live phone call.\n\n"
        f"Your instructions:\n{base}\n\n"
        "Respond naturally in 1-3 sentences as on a phone call. "
        "Respond ONLY with what you would say — no stage directions."
    )


def _should_end_conversation(text: str, *, turn_index: int, min_turns: int = 2) -> bool:
    if turn_index < min_turns:
        return False
    return bool(_GOODBYE_RE.search(text or ""))


def _caller_messages(system_prompt: str, transcript: list[dict[str, str]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for entry in transcript:
        speaker = entry.get("speaker")
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        if speaker == "Speaker 1":
            messages.append({"role": "assistant", "content": text})
        else:
            messages.append({"role": "user", "content": text})
    if len(messages) == 1:
        messages.append(
            {
                "role": "user",
                "content": "The call has just connected. Start the conversation.",
            }
        )
    return messages


def _agent_messages(system_prompt: str, transcript: list[dict[str, str]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for entry in transcript:
        speaker = entry.get("speaker")
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        if speaker == "Speaker 2":
            messages.append({"role": "assistant", "content": text})
        else:
            messages.append({"role": "user", "content": text})
    return messages


def _resolve_voice_bundle_llm(
    db: Session,
    *,
    voice_bundle: VoiceBundle,
    organization_id: UUID,
) -> tuple[ModelProvider, str, Optional[dict], Optional[UUID]]:
    raw_provider = voice_bundle.llm_provider
    if raw_provider is None:
        raise ValueError("Voice bundle is missing llm_provider")
    provider = (
        raw_provider
        if isinstance(raw_provider, ModelProvider)
        else ModelProvider(str(raw_provider).lower())
    )
    model = (voice_bundle.llm_model or "").strip()
    if not model:
        raise ValueError("Voice bundle is missing llm_model")
    llm_config = voice_bundle.llm_config if isinstance(voice_bundle.llm_config, dict) else None
    credential_id = getattr(voice_bundle, "llm_credential_id", None)
    return provider, model, llm_config, credential_id


def _generate_turn(
    *,
    messages: list[dict[str, str]],
    llm_provider: ModelProvider,
    llm_model: str,
    organization_id: UUID,
    db: Session,
    llm_config: Optional[dict],
    credential_id: Optional[UUID],
) -> str:
    result = llm_service.generate_response(
        messages=messages,
        llm_provider=llm_provider,
        llm_model=llm_model,
        organization_id=organization_id,
        db=db,
        llm_config=llm_config,
        task_defaults={"temperature": 0.7, "max_tokens": 300},
        credential_id=credential_id,
    )
    text = (result.get("text") or "").strip()
    if not text:
        raise ValueError("LLM returned an empty simulation response")
    return text


def run_llm_to_llm_evaluator_simulation(
    *,
    evaluator: Evaluator,
    result: EvaluatorResult,
    agent: Agent,
    persona: Persona,
    scenario: Scenario,
    organization_id: UUID,
    db: Session,
) -> dict[str, Any]:
    """Run a text simulation and populate the evaluator result transcript."""
    if not agent.voice_bundle_id:
        raise ValueError("Agent does not have a voice bundle configured")

    voice_bundle = (
        db.query(VoiceBundle)
        .filter(
            VoiceBundle.id == agent.voice_bundle_id,
            VoiceBundle.organization_id == organization_id,
        )
        .first()
    )
    if not voice_bundle:
        raise ValueError(f"Voice bundle {agent.voice_bundle_id} not found")

    llm_provider, llm_model, llm_config, credential_id = _resolve_voice_bundle_llm(
        db,
        voice_bundle=voice_bundle,
        organization_id=organization_id,
    )

    max_turns = resolve_persona_max_turns(persona)
    persona_description = build_persona_description_for_bridge(persona)
    caller_system = build_test_agent_system_prompt(
        agent,
        persona,
        scenario,
        persona_description=persona_description,
        max_turns=max_turns,
    )
    agent_system = _build_agent_system_prompt(agent)

    caller_ctx = usage_context_for_test_agent_simulation(
        organization_id=organization_id,
        workspace_id=evaluator.workspace_id,
        agent_id=agent.id,
        evaluator_id=evaluator.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        evaluator_result_id=result.id,
        provider_platform="internal",
    )
    agent_ctx = LLMUsageContext(
        organization_id=organization_id,
        workspace_id=evaluator.workspace_id,
        product_section=LLMUsageProductSection.EVALUATORS,
        resource_id=evaluator.id,
        resource_type="evaluator",
        extra={
            "agent_id": str(agent.id),
            "evaluator_id": str(evaluator.id),
            "persona_id": str(persona.id),
            "scenario_id": str(scenario.id),
            "evaluator_result_id": str(result.id),
            "synthetic_testing": "pre_prod",
            "simulation_leg": "production_agent",
            "provider_platform": "internal",
        },
    )

    transcript: list[dict[str, str]] = []
    first_message = f"Hello, this is {persona.name} calling."
    transcript.append({"speaker": "Speaker 1", "text": first_message})

    exchanges = 0
    while exchanges < max_turns:
        with llm_usage_context(agent_ctx):
            agent_text = _generate_turn(
                messages=_agent_messages(agent_system, transcript),
                llm_provider=llm_provider,
                llm_model=llm_model,
                organization_id=organization_id,
                db=db,
                llm_config=llm_config,
                credential_id=credential_id,
            )
        transcript.append({"speaker": "Speaker 2", "text": agent_text})
        exchanges += 1
        if _should_end_conversation(agent_text, turn_index=exchanges):
            break

        with llm_usage_context(caller_ctx):
            caller_text = _generate_turn(
                messages=_caller_messages(caller_system, transcript),
                llm_provider=llm_provider,
                llm_model=llm_model,
                organization_id=organization_id,
                db=db,
                llm_config=llm_config,
                credential_id=credential_id,
            )
        transcript.append({"speaker": "Speaker 1", "text": caller_text})
        exchanges += 1
        if _should_end_conversation(caller_text, turn_index=exchanges):
            break

    transcription = "\n".join(
        f"{entry['speaker']}: {entry['text']}" for entry in transcript if entry.get("text")
    )
    speaker_segments = [
        {
            "speaker": entry["speaker"],
            "text": entry["text"],
            "start": float(idx),
            "end": float(idx) + 1.0,
        }
        for idx, entry in enumerate(transcript)
    ]

    result.transcription = transcription
    result.speaker_segments = speaker_segments
    result.provider_platform = "internal"
    result.call_data = {
        "source": "llm_to_llm_simulation",
        "simulation": "llm_to_llm",
        "exchanges": exchanges,
        "messages": transcript,
    }
    result.duration_seconds = float(max(1, len(transcript)))

    logger.info(
        "[LLM simulation] Completed evaluator {} result {} with {} transcript lines",
        evaluator.evaluator_id,
        result.result_id,
        len(transcript),
    )
    return {
        "transcript_lines": len(transcript),
        "exchanges": exchanges,
        "provider_platform": "internal",
    }
