"""Text-based LLM-to-LLM simulation for evaluator runs without an external voice provider."""

from __future__ import annotations

import re
import time
from typing import Any, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import Agent, Evaluator, EvaluatorResult, Persona, Scenario
from app.services.agents.chat_connection import normalized_chat_connection_type
from app.services.agents.chat_llm_config import resolve_simulation_llm
from app.services.agents.chat_connection_config_store import chat_connection_config_for_runtime
from app.services.agents.chat_production_leg import (
    generate_production_chat_reply,
    uses_live_production_leg,
)
from app.services.agents.messaging_channel_chat import is_meta_whatsapp_live_cfg
from app.services.agents.provider_platform_chat import (
    ProviderChatState,
    close_provider_chat_session,
)
from app.services.testing.evaluator_simulation_errors import (
    ProductionChatLegError,
    TestAgentLlmLegError,
)
from app.models.enums import ModelProvider
from app.services.ai.llm_service import llm_service
from app.services.testing.test_agent_simulation_prompt import (
    build_persona_description_for_bridge,
    build_test_agent_system_prompt,
    is_chat_agent,
    resolve_persona_max_turns,
)
from app.services.testing.test_agent_template import (
    TestAgentFirstMessage,
    ensure_opening_includes_persona_name,
    resolve_caller_opening_text,
    resolve_first_message_from_agent,
    should_caller_speak_first,
)
from app.services.usage.context import (
    LLMUsageContext,
    LLMUsageProductSection,
    llm_usage_context,
    usage_context_for_test_agent_simulation,
)

_GOODBYE_RE = re.compile(
    r"\b(goodbye|bye|talk\s+to\s+you\s+later|have\s+a\s+(?:good|great)\s+(?:day|one))\b",
    re.IGNORECASE,
)
_THANKS_CLOSING_RE = re.compile(
    r"\b(?:thank\s+you|thanks)\b\s*[.!]?\s*$",
    re.IGNORECASE,
)

_SIMULATION_LLM_RETRIES = 3
_SIMULATION_TASK_DEFAULTS = {"temperature": 0.7, "max_tokens": 2048}


def _uses_meta_whatsapp_live_customer_on_phone(agent: Agent) -> bool:
    if not uses_live_production_leg(agent):
        return False
    cfg = chat_connection_config_for_runtime(agent.chat_connection_config)
    return is_meta_whatsapp_live_cfg(cfg)


def _production_turn_needs_user_seed(transcript: list[dict[str, str]]) -> bool:
    if not transcript:
        return True
    last = transcript[-1]
    speaker = (last.get("speaker") or "").strip()
    text = (last.get("text") or "").strip()
    return speaker != "Speaker 1" or not text


def _build_eval_user_opener(
    *,
    agent: Agent,
    persona: Persona,
    first_message_config: TestAgentFirstMessage,
    scenario_first_message: Optional[str],
) -> str:
    persona_name = (persona.name or "Test Caller").strip()
    opening: Optional[str] = None
    if should_caller_speak_first(first_message_config):
        opening = resolve_caller_opening_text(
            first_message=first_message_config,
            persona_name=persona_name,
            scenario_first_message=scenario_first_message,
        )
        phone_default = f"Hello, this is {persona_name} calling."
        if is_chat_agent(agent) and opening == phone_default:
            opening = f"Hi, I'm {persona_name}. I need some help."
    else:
        if scenario_first_message and str(scenario_first_message).strip():
            opening = ensure_opening_includes_persona_name(
                str(scenario_first_message).strip(),
                persona_name,
            )
        else:
            opening = f"Hi, I'm {persona_name}. I need some help."
    if not (opening or "").strip():
        opening = f"Hi, I'm {persona_name}. I need some help."
    return opening.strip()


def _should_end_conversation(text: str, *, turn_index: int, min_turns: int = 2) -> bool:
    if turn_index < min_turns:
        return False
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _GOODBYE_RE.search(stripped):
        return True
    return bool(_THANKS_CLOSING_RE.search(stripped))


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


def _generate_turn(
    *,
    messages: list[dict[str, str]],
    llm_provider: ModelProvider,
    llm_model: str,
    organization_id: UUID,
    db: Session,
    llm_config: Optional[dict],
    credential_id: Optional[UUID],
    leg_label: str = "simulation",
) -> str:
    last_result: Optional[dict[str, Any]] = None
    for attempt in range(_SIMULATION_LLM_RETRIES):
        override_llm_config: Optional[dict[str, Any]] = None
        if attempt > 0:
            override_llm_config = {
                "temperature": min(1.0, 0.7 + 0.15 * attempt),
            }
            time.sleep(0.35 * attempt)
        try:
            result = llm_service.generate_response(
                messages=messages,
                llm_provider=llm_provider,
                llm_model=llm_model,
                organization_id=organization_id,
                db=db,
                llm_config=llm_config,
                task_defaults=_SIMULATION_TASK_DEFAULTS,
                override_llm_config=override_llm_config,
                credential_id=credential_id,
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"{leg_label} failed ({llm_provider.value}/{llm_model}): {exc}"
            ) from exc
        last_result = result
        text = (result.get("text") or "").strip()
        if text:
            return text
        logger.warning(
            "[LLM simulation] Empty {} response (attempt {}/{}, provider={}, model={}, finish_reason={})",
            leg_label,
            attempt + 1,
            _SIMULATION_LLM_RETRIES,
            llm_provider.value,
            llm_model,
            result.get("finish_reason"),
        )

    result = last_result or {}
    refusal = (result.get("refusal") or "").strip()
    if refusal:
        raise ValueError(
            f"LLM refused the simulation request ({leg_label}; "
            f"provider={llm_provider.value}, model={llm_model}): {refusal}"
        )
    finish_reason = result.get("finish_reason")
    hint = ""
    if finish_reason == "length" or result.get("truncated"):
        hint = (
            " The model hit the output token limit before producing visible text "
            "(common with reasoning models like gpt-oss-120b or gpt-5-mini); "
            "raise max_tokens or set reasoning_effort=minimal in test agent LLM config."
        )
    elif finish_reason:
        hint = f" finish_reason={finish_reason}."
    raise ValueError(
        f"LLM returned an empty simulation response ({leg_label}; "
        f"provider={llm_provider.value}, model={llm_model}).{hint} "
        f"Tried {_SIMULATION_LLM_RETRIES} times. "
        "Check provider rate limits and worker logs for [LLMService] empty assistant text."
    )


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
    conn_type = normalized_chat_connection_type(agent)

    test_llm = resolve_simulation_llm(
        db, agent=agent, organization_id=organization_id, leg="test"
    )
    provider_chat_state = ProviderChatState()
    production_leg_meta: dict[str, Any] = {}

    max_turns = resolve_persona_max_turns(persona)
    persona_description = build_persona_description_for_bridge(persona)
    caller_system = build_test_agent_system_prompt(
        agent,
        persona,
        scenario,
        persona_description=persona_description,
        max_turns=max_turns,
    )
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
    chat_mode = is_chat_agent(agent)
    first_message_config = resolve_first_message_from_agent(agent)
    scenario_first_message = None
    if isinstance(scenario.required_info, dict):
        scenario_first_message = scenario.required_info.get("first_message")
    exchanges = 0

    def _write_transcript_to_result() -> None:
        result.transcription = "\n".join(
            f"{entry['speaker']}: {entry['text']}"
            for entry in transcript
            if entry.get("text")
        )
        result.speaker_segments = [
            {
                "speaker": entry["speaker"],
                "text": entry["text"],
                "start": float(idx),
                "end": float(idx) + 1.0,
            }
            for idx, entry in enumerate(transcript)
        ]
        result.provider_platform = "internal"
        result.call_data = {
            "source": "llm_to_llm_simulation",
            "simulation": "llm_to_llm",
            "modality": "chat" if chat_mode else "voice",
            "chat_connection_type": conn_type,
            **production_leg_meta,
            "test_llm_source": test_llm.source,
            "exchanges": exchanges,
            "messages": transcript,
            "partial": exchanges < max_turns,
        }
        result.duration_seconds = float(max(1, len(transcript)))

    try:
        while exchanges < max_turns:
            if (
                uses_live_production_leg(agent)
                and not _uses_meta_whatsapp_live_customer_on_phone(agent)
                and _production_turn_needs_user_seed(transcript)
            ):
                transcript.append(
                    {
                        "speaker": "Speaker 1",
                        "text": _build_eval_user_opener(
                            agent=agent,
                            persona=persona,
                            first_message_config=first_message_config,
                            scenario_first_message=scenario_first_message,
                        ),
                    }
                )
            elif (
                not uses_live_production_leg(agent)
                and not transcript
                and should_caller_speak_first(first_message_config)
            ):
                opener = _build_eval_user_opener(
                    agent=agent,
                    persona=persona,
                    first_message_config=first_message_config,
                    scenario_first_message=scenario_first_message,
                )
                transcript.append({"speaker": "Speaker 1", "text": opener})

            try:
                with llm_usage_context(agent_ctx):
                    agent_text, leg_meta = generate_production_chat_reply(
                        db,
                        agent=agent,
                        organization_id=organization_id,
                        transcript=transcript,
                        provider_state=provider_chat_state,
                        evaluator_result=result,
                    )
            except Exception as exc:
                leg = (
                    provider_chat_state.extra.get("production_leg")
                    or provider_chat_state.platform
                    or conn_type
                )
                raise ProductionChatLegError(
                    str(leg),
                    f"Production chat leg failed ({leg}): {exc}",
                ) from exc
            production_leg_meta.update(leg_meta)
            transcript.append({"speaker": "Speaker 2", "text": agent_text})
            exchanges += 1
            if _should_end_conversation(agent_text, turn_index=exchanges):
                break

            if _uses_meta_whatsapp_live_customer_on_phone(agent):
                continue

            try:
                with llm_usage_context(caller_ctx):
                    caller_text = _generate_turn(
                        messages=_caller_messages(caller_system, transcript),
                        llm_provider=test_llm.provider,
                        llm_model=test_llm.model,
                        organization_id=organization_id,
                        db=db,
                        llm_config=test_llm.llm_config,
                        credential_id=test_llm.credential_id,
                        leg_label="Simulated customer (test agent LLM)",
                    )
            except Exception as exc:
                raise TestAgentLlmLegError(f"Test agent LLM failed: {exc}") from exc
            transcript.append({"speaker": "Speaker 1", "text": caller_text})
            exchanges += 1
            if _should_end_conversation(caller_text, turn_index=exchanges):
                break
    except Exception:
        if transcript:
            _write_transcript_to_result()
        raise
    finally:
        try:
            close_provider_chat_session(
                db,
                agent=agent,
                organization_id=organization_id,
                state=provider_chat_state,
            )
        except Exception:
            logger.warning(
                "[LLM simulation] Provider chat session teardown failed for evaluator {}",
                evaluator.evaluator_id,
            )

    _write_transcript_to_result()
    if isinstance(result.call_data, dict):
        result.call_data["partial"] = False

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
