"""Voice red team calls through the web-call bridge (Retell / Vapi / ElevenLabs).

The attacker speaks through the test-agent bridge with ``caller_override``: the red team
prompt replaces the persona/scenario prompt, and the poll task skips metric evaluation
because the red team judge scores the transcript. Each call gets an ``EvaluatorResult``
(no evaluator) so the recording and provider transcript live where the rest of the app
expects them.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent, EvaluatorResult, Persona, RedTeamRun
from app.models.enums import EvaluatorResultStatus


class VoiceAttackError(RuntimeError):
    pass


def voice_supported(agent: Agent) -> bool:
    """Red team voice needs the web-call bridge: a voice bundle and a Retell/Vapi/ElevenLabs agent."""
    return bool(agent.voice_bundle_id and agent.voice_ai_integration_id and agent.voice_ai_agent_id)


def pick_persona(db: Session, agent: Agent, persona_id: Optional[UUID]) -> Optional[Persona]:
    """Persona whose TTS voice the attacker uses; must match the agent's voice bundle TTS."""
    from app.services.evaluators.evaluator_helpers import require_matching_agent_persona_tts

    query = db.query(Persona).filter(
        Persona.organization_id == agent.organization_id,
        Persona.workspace_id == agent.workspace_id,
    )
    candidates = [query.filter(Persona.id == persona_id).first()] if persona_id else query.order_by(Persona.created_at).all()
    for persona in candidates:
        if persona is None or (getattr(persona, "simulation_medium", "voice") or "voice") != "voice":
            continue
        try:
            require_matching_agent_persona_tts(db, agent, persona)
        except Exception:
            continue
        return persona
    return None


def _unique_result_id(db: Session) -> str:
    for _ in range(100):
        candidate = f"{random.randint(100000, 999999)}"
        if not db.query(EvaluatorResult.id).filter(EvaluatorResult.result_id == candidate).first():
            return candidate
    raise VoiceAttackError("Could not allocate an evaluator result id")


def _transcript_from_segments(segments: Any) -> list[dict[str, Any]]:
    transcript: list[dict[str, Any]] = []
    for segment in segments or []:
        if not isinstance(segment, dict):
            continue
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        role = "attacker" if segment.get("speaker") == "Speaker 1" else "agent"
        if transcript and transcript[-1]["role"] == role:
            transcript[-1]["text"] += " " + text
        else:
            transcript.append({"role": role, "text": text})
    return transcript


def run_voice_conversation(
    db: Session,
    *,
    run: RedTeamRun,
    agent: Agent,
    persona: Persona,
    system_prompt: str,
    first_message: Optional[str],
    goal: str,
    attack_label: str,
) -> tuple[list[dict[str, Any]], EvaluatorResult]:
    """Place one bridged voice call and return (transcript, evaluator_result)."""
    from app.services.testing.test_agent_bridge_service import test_agent_bridge_service

    result = EvaluatorResult(
        result_id=_unique_result_id(db),
        organization_id=run.organization_id,
        workspace_id=run.workspace_id,
        agent_id=agent.id,
        persona_id=persona.id,
        name=f"Red team {run.run_id}: {attack_label}"[:200],
        status=EvaluatorResultStatus.QUEUED.value,
        call_data={"red_team": {"run_id": run.run_id, "red_team_run_id": str(run.id)}},
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    max_minutes = int((run.config or {}).get("max_call_minutes") or 10)
    caller_override = {
        "agent_id": agent.id,
        "persona_id": persona.id,
        "run_ref": run.run_id,
        "goal": goal,
        "caller_system_prompt": system_prompt,
        "first_message": first_message,
        "max_call_seconds": max_minutes * 60,
        "skip_metric_evaluation": True,
    }
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            test_agent_bridge_service.bridge_test_agent_to_voice_agent(
                evaluator_id=None,
                evaluator_result_id=result.id,
                organization_id=run.organization_id,
                db=db,
                caller_override=caller_override,
            )
        )
    except Exception as exc:
        raise VoiceAttackError(f"Voice call failed: {exc}") from exc
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    db.refresh(result)
    transcript = _transcript_from_segments(result.speaker_segments)
    if not transcript and result.transcription:
        transcript = [{"role": "agent", "text": result.transcription}]
    if not transcript:
        raise VoiceAttackError(result.error_message or "The call produced no transcript")
    return transcript, result
