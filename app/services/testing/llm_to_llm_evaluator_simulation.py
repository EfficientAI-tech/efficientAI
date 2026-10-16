"""Text-based LLM-to-LLM simulation for evaluator runs without an external voice provider."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import Agent, Evaluator, EvaluatorResult, Persona, Scenario
from app.services.agents.chat_connection import normalized_chat_connection_type
from app.services.agents.chat_llm_config import ResolvedSimulationLlm, resolve_simulation_llm
from app.services.agents.chat_production_leg import (
    generate_production_chat_reply,
    uses_live_production_leg,
)
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


_CUSTOMER_CHAT_TURN_NUDGE = (
    "The company's agent sent the last message above. "
    "Write the customer's next chat reply only (plain text, stay in character as the customer)."
)


def _caller_messages(
    system_prompt: str,
    transcript: list[dict[str, str]],
    *,
    chat: bool = False,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for entry in transcript:
        speaker = entry.get("speaker")
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        if chat:
            if speaker == "Speaker 1":
                messages.append({"role": "user", "content": text})
            else:
                messages.append({"role": "assistant", "content": text})
        elif speaker == "Speaker 1":
            messages.append({"role": "assistant", "content": text})
        else:
            messages.append({"role": "user", "content": text})
    if len(messages) == 1:
        messages.append(
            {
                "role": "user",
                "content": (
                    "Start the conversation as the customer (one short message)."
                    if chat
                    else "The call has just connected. Start the conversation."
                ),
            }
        )
    elif chat:
        messages.append({"role": "user", "content": _CUSTOMER_CHAT_TURN_NUDGE})
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


def _generate_test_customer_turn(
    *,
    messages: list[dict[str, str]],
    agent: Agent,
    organization_id: UUID,
    db: Session,
    llm_provider: ModelProvider,
    llm_model: str,
    llm_config: Optional[dict],
    credential_id: Optional[UUID],
) -> tuple[str, list[dict[str, Any]]]:
    """Simulated customer turn; uses knowledge-base tools when the agent has ready docs."""
    leg_label = "Simulated customer (test agent LLM)"
    kb_tool_calls: list[dict[str, Any]] = []
    workspace_id = agent.workspace_id
    if workspace_id:
        from app.services.knowledge_bases.chat_tools import (
            generate_production_reply_with_knowledge_tools,
        )
        from app.services.knowledge_bases.retrieval import agent_has_ready_knowledge

        if agent_has_ready_knowledge(db, agent_id=agent.id):
            try:
                text, kb_tool_calls = generate_production_reply_with_knowledge_tools(
                    db,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    agent_id=agent.id,
                    messages=messages,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    llm_config=llm_config,
                    credential_id=credential_id,
                    task_defaults=_SIMULATION_TASK_DEFAULTS,
                )
            except RuntimeError as exc:
                raise RuntimeError(
                    f"{leg_label} failed ({llm_provider.value}/{llm_model}): {exc}"
                ) from exc
            if (text or "").strip():
                return text.strip(), kb_tool_calls
    text = _generate_turn(
        messages=messages,
        llm_provider=llm_provider,
        llm_model=llm_model,
        organization_id=organization_id,
        db=db,
        llm_config=llm_config,
        credential_id=credential_id,
        leg_label=leg_label,
    )
    return text, kb_tool_calls


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


@dataclass
class TextConversation:
    """Mutable conversation state; stays readable when ``run_text_conversation`` raises."""

    transcript: list[dict[str, str]] = field(default_factory=list)
    exchanges: int = 0
    max_turns: int = 0
    production_leg_meta: dict[str, Any] = field(default_factory=dict)
    test_kb_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    test_llm_source: str = ""


# Called after every appended turn with the transcript entry and LLM/endpoint latency in seconds.
OnTurn = Callable[[dict[str, str], float], None]


def run_text_conversation(
    *,
    agent: Agent,
    persona: Persona,
    scenario: Scenario,
    organization_id: UUID,
    db: Session,
    conversation: TextConversation,
    caller_ctx: LLMUsageContext,
    agent_ctx: LLMUsageContext,
    evaluator_result: Optional[EvaluatorResult] = None,
    test_llm_override: Optional[ResolvedSimulationLlm] = None,
    production_llm_override: Optional[ResolvedSimulationLlm] = None,
    on_turn: Optional[OnTurn] = None,
) -> TextConversation:
    """Alternate test-agent and production-agent turns until goodbye or ``max_turns``."""
    test_llm = test_llm_override or resolve_simulation_llm(
        db, agent=agent, organization_id=organization_id, leg="test"
    )
    conversation.test_llm_source = test_llm.source
    provider_chat_state = ProviderChatState()
    conversation.max_turns = resolve_persona_max_turns(persona)
    caller_system = build_test_agent_system_prompt(
        agent,
        persona,
        scenario,
        persona_description=build_persona_description_for_bridge(persona),
        max_turns=conversation.max_turns,
    )
    transcript = conversation.transcript
    first_message_config = resolve_first_message_from_agent(agent)
    scenario_first_message = None
    if isinstance(scenario.required_info, dict):
        scenario_first_message = scenario.required_info.get("first_message")
    conn_type = normalized_chat_connection_type(agent)

    def _append(speaker: str, text: str, started: float) -> None:
        entry = {"speaker": speaker, "text": text}
        transcript.append(entry)
        if on_turn is not None:
            on_turn(entry, time.monotonic() - started)

    try:
        while conversation.exchanges < conversation.max_turns:
            if uses_live_production_leg(agent) and _production_turn_needs_user_seed(transcript):
                _append(
                    "Speaker 1",
                    _build_eval_user_opener(
                        agent=agent,
                        persona=persona,
                        first_message_config=first_message_config,
                        scenario_first_message=scenario_first_message,
                    ),
                    time.monotonic(),
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
                _append("Speaker 1", opener, time.monotonic())

            started = time.monotonic()
            try:
                with llm_usage_context(agent_ctx):
                    agent_text, leg_meta = generate_production_chat_reply(
                        db,
                        agent=agent,
                        organization_id=organization_id,
                        transcript=transcript,
                        provider_state=provider_chat_state,
                        evaluator_result=evaluator_result,
                        llm_override=production_llm_override,
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
            conversation.production_leg_meta.update(leg_meta)
            _append("Speaker 2", agent_text, started)
            conversation.exchanges += 1
            if _should_end_conversation(agent_text, turn_index=conversation.exchanges):
                break

            started = time.monotonic()
            try:
                with llm_usage_context(caller_ctx):
                    caller_text, turn_kb_calls = _generate_test_customer_turn(
                        messages=_caller_messages(
                            caller_system, transcript, chat=is_chat_agent(agent)
                        ),
                        agent=agent,
                        organization_id=organization_id,
                        db=db,
                        llm_provider=test_llm.provider,
                        llm_model=test_llm.model,
                        llm_config=test_llm.llm_config,
                        credential_id=test_llm.credential_id,
                    )
                    if turn_kb_calls:
                        conversation.test_kb_tool_calls.extend(turn_kb_calls)
            except Exception as exc:
                raise TestAgentLlmLegError(f"Test agent LLM failed: {exc}") from exc
            _append("Speaker 1", caller_text, started)
            conversation.exchanges += 1
            if _should_end_conversation(caller_text, turn_index=conversation.exchanges):
                break
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
                "[LLM simulation] Provider chat session teardown failed for agent {}",
                agent.id,
            )
    return conversation


def write_conversation_to_result(
    result: EvaluatorResult,
    conversation: TextConversation,
    *,
    agent: Agent,
    extra_call_data: Optional[dict[str, Any]] = None,
) -> None:
    """Store transcript, speaker segments and call_data on an evaluator result."""
    transcript = conversation.transcript
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
    call_data: dict[str, Any] = {
        "source": "llm_to_llm_simulation",
        "simulation": "llm_to_llm",
        "modality": "chat" if is_chat_agent(agent) else "voice",
        "chat_connection_type": normalized_chat_connection_type(agent),
        **conversation.production_leg_meta,
        "test_llm_source": conversation.test_llm_source,
        "exchanges": conversation.exchanges,
        "messages": transcript,
        "partial": conversation.exchanges < conversation.max_turns,
    }
    if conversation.test_kb_tool_calls:
        call_data["test_agent_knowledge_base_tool_calls"] = conversation.test_kb_tool_calls
    if extra_call_data:
        call_data.update(extra_call_data)
    result.call_data = call_data
    result.duration_seconds = float(max(1, len(transcript)))


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

    conversation = TextConversation()
    try:
        run_text_conversation(
            agent=agent,
            persona=persona,
            scenario=scenario,
            organization_id=organization_id,
            db=db,
            conversation=conversation,
            caller_ctx=caller_ctx,
            agent_ctx=agent_ctx,
            evaluator_result=result,
        )
    except Exception:
        if conversation.transcript:
            write_conversation_to_result(result, conversation, agent=agent)
        raise

    write_conversation_to_result(result, conversation, agent=agent)
    if isinstance(result.call_data, dict):
        result.call_data["partial"] = False

    logger.info(
        "[LLM simulation] Completed evaluator {} result {} with {} transcript lines",
        evaluator.evaluator_id,
        result.result_id,
        len(conversation.transcript),
    )
    return {
        "transcript_lines": len(conversation.transcript),
        "exchanges": conversation.exchanges,
        "provider_platform": "internal",
    }
