"""Chat conversations between a red team caller and the agent under test.

The agent side goes through ``generate_production_chat_reply``, so every chat connection
type (internal LLM, provider chat, customer API / websocket, messaging channels) is
attacked exactly the way regular chat simulations reach it.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import Agent, RedTeamRun
from app.services.agents.chat_llm_config import ResolvedSimulationLlm
from app.services.red_team.llm import RedTeamLlmError, complete, usage_context
from app.services.red_team.prompts import END_MARKER
from app.services.usage.context import llm_usage_context

_REFUSAL_RE = re.compile(
    r"^\s*(?:i'?m sorry|sorry|i can(?:no|')t|i cannot|i won'?t|i am unable|i'?m unable|as an ai)\b",
    re.IGNORECASE,
)

# role: attacker | agent
Transcript = list[dict[str, Any]]


class ConversationStopped(Exception):
    """Raised when the run was cancelled mid-conversation."""


def looks_like_refusal(text: str) -> bool:
    """The attacker model declined to play its role (not the agent under test)."""
    return bool(_REFUSAL_RE.match(text or "")) and len(text or "") < 400


def _attacker_messages(system_prompt: str, transcript: Transcript) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt}]
    for entry in transcript:
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        messages.append({"role": "assistant" if entry["role"] == "attacker" else "user", "content": text})
    if len(messages) == 1:
        messages.append({"role": "user", "content": "The conversation has just started. Write your first message."})
    return messages


def _speaker_transcript(transcript: Transcript) -> list[dict[str, Any]]:
    """Production leg format: Speaker 1 = caller, Speaker 2 = agent."""
    return [
        {"speaker": "Speaker 1" if e["role"] == "attacker" else "Speaker 2", "text": e.get("text") or ""}
        for e in transcript
    ]


def next_attacker_turn(
    db: Session,
    *,
    run: RedTeamRun,
    llm: ResolvedSimulationLlm,
    system_prompt: str,
    transcript: Transcript,
    seed_opener: Optional[str],
    attack_id: Optional[UUID],
) -> tuple[str, bool]:
    """Return (text, ended). Falls back to the seed opener when the attacker model refuses turn one."""
    first_turn = not any(e["role"] == "attacker" for e in transcript)
    try:
        with llm_usage_context(usage_context(run, leg="attacker", attack_id=attack_id)):
            text = complete(
                db,
                organization_id=run.organization_id,
                llm=llm,
                messages=_attacker_messages(system_prompt, transcript),
            )
    except RedTeamLlmError:
        if first_turn and seed_opener:
            logger.warning("[RedTeam] Attacker LLM failed on turn one; using seed opener")
            return seed_opener, False
        raise
    if looks_like_refusal(text):
        if first_turn and seed_opener:
            return seed_opener, False
        raise RedTeamLlmError(f"Attacker model refused to continue: {text[:200]}")
    ended = END_MARKER in text
    text = text.replace(END_MARKER, "").strip()
    return text, ended


def run_chat_conversation(
    db: Session,
    *,
    run: RedTeamRun,
    agent: Agent,
    attacker_llm: ResolvedSimulationLlm,
    system_prompt: str,
    max_turns: int,
    seed_opener: Optional[str] = None,
    attack_id: Optional[UUID] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    on_update: Optional[Callable[[Transcript], None]] = None,
) -> Transcript:
    """Alternate caller and agent messages until the caller ends, ``max_turns`` or cancel.

    ``max_turns`` counts messages from both sides. Returns the transcript; on errors the
    partial transcript is attached to the raised exception as ``exc.transcript``.
    """
    from app.services.agents.chat_production_leg import (
        generate_production_chat_reply,
        uses_live_production_leg,
    )
    from app.services.agents.provider_platform_chat import (
        ProviderChatState,
        close_provider_chat_session,
    )

    transcript: Transcript = []
    provider_state = ProviderChatState()
    toolset = None
    if not uses_live_production_leg(agent):
        from app.services.tools.toolset import build_agent_toolset

        toolset = build_agent_toolset(
            db,
            agent=agent,
            organization_id=run.organization_id,
            llm_model=agent.main_llm_model,
        )

    def _changed() -> None:
        if on_update is not None:
            on_update(transcript)

    try:
        while len(transcript) < max_turns:
            if should_stop and should_stop():
                raise ConversationStopped()
            text, ended = next_attacker_turn(
                db,
                run=run,
                llm=attacker_llm,
                system_prompt=system_prompt,
                transcript=transcript,
                seed_opener=seed_opener,
                attack_id=attack_id,
            )
            if text:
                transcript.append({"role": "attacker", "text": text})
                _changed()
            if ended or not text or len(transcript) >= max_turns:
                break

            with llm_usage_context(usage_context(run, leg="agent", attack_id=attack_id)):
                reply, meta = generate_production_chat_reply(
                    db,
                    agent=agent,
                    organization_id=run.organization_id,
                    transcript=_speaker_transcript(transcript),
                    provider_state=provider_state,
                    toolset=toolset,
                )
            entry: dict[str, Any] = {"role": "agent", "text": reply or ""}
            tool_calls = meta.pop("tool_calls", None) if isinstance(meta, dict) else None
            if tool_calls:
                entry["tool_calls"] = tool_calls
            transcript.append(entry)
            _changed()
    except Exception as exc:
        exc.transcript = transcript  # type: ignore[attr-defined]
        raise
    finally:
        if toolset is not None:
            try:
                toolset.close()
            except Exception:
                pass
        try:
            close_provider_chat_session(db, agent=agent, organization_id=run.organization_id, state=provider_state)
        except Exception:
            logger.warning("[RedTeam] Provider chat session teardown failed for agent {}", agent.id)
    return transcript
