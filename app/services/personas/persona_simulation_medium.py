"""Voice vs text personas (simulation_medium on personas table)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

from app.models.database import Agent, Persona
from app.models.enums import CallMediumEnum, SimulationMediumEnum


def normalized_simulation_medium(raw: Any) -> str:
    if raw is None:
        return SimulationMediumEnum.VOICE.value
    if hasattr(raw, "value"):
        return str(raw.value).lower()
    return str(raw).lower()


def persona_simulation_medium(persona: Persona) -> str:
    return normalized_simulation_medium(getattr(persona, "simulation_medium", None))


def infer_simulation_medium_from_fields(
    *,
    explicit: Any,
    tts_provider: Optional[str],
) -> str:
    if explicit is not None:
        medium = normalized_simulation_medium(explicit)
        if medium in (SimulationMediumEnum.VOICE.value, SimulationMediumEnum.TEXT.value):
            return medium
    if tts_provider and str(tts_provider).strip():
        return SimulationMediumEnum.VOICE.value
    return SimulationMediumEnum.TEXT.value


def apply_persona_medium_defaults(
    *,
    simulation_medium: Any,
    tts_provider: Optional[str],
    tts_voice_id: Optional[str],
    tts_voice_name: Optional[str],
    is_custom: bool,
    background_noise_source: Any,
) -> dict[str, Any]:
    medium = infer_simulation_medium_from_fields(
        explicit=simulation_medium, tts_provider=tts_provider
    )
    if medium == SimulationMediumEnum.TEXT.value:
        return {
            "simulation_medium": medium,
            "tts_provider": None,
            "tts_voice_id": None,
            "tts_voice_name": None,
            "is_custom": False,
            "background_noise_source": "none",
            "background_noise_preset": None,
            "background_noise_volume": None,
            "background_noise_asset_id": None,
            "background_noise_s3_key": None,
        }
    return {"simulation_medium": medium}


def validate_persona_medium_fields(
    *,
    simulation_medium: str,
    tts_provider: Optional[str],
) -> None:
    medium = normalized_simulation_medium(simulation_medium)
    if medium == SimulationMediumEnum.TEXT.value:
        if tts_provider and str(tts_provider).strip():
            raise HTTPException(
                status_code=400,
                detail="Text chat customer prompts cannot have a TTS provider. Use simulation_medium=text.",
            )
        return
    if medium != SimulationMediumEnum.VOICE.value:
        raise HTTPException(status_code=400, detail=f"Invalid simulation_medium: {simulation_medium}")


def expected_persona_medium_for_agent(agent: Agent) -> str:
    medium = (agent.call_medium or CallMediumEnum.PHONE_CALL.value).lower()
    if medium == CallMediumEnum.CHAT.value:
        return SimulationMediumEnum.TEXT.value
    return SimulationMediumEnum.VOICE.value


def validate_agent_persona_simulation_medium(agent: Agent, persona: Persona) -> None:
    expected = expected_persona_medium_for_agent(agent)
    actual = persona_simulation_medium(persona)
    if actual == expected:
        return
    if expected == SimulationMediumEnum.TEXT.value:
        raise HTTPException(
            status_code=400,
            detail=(
                "Chat agents require customer prompts (simulation_medium=text). "
                "Caller personas with voice/TTS are for phone and web voice agents."
            ),
        )
    raise HTTPException(
        status_code=400,
        detail=(
            "Voice agents require caller personas (simulation_medium=voice). "
            "Text customer prompts are only for chat agents."
        ),
    )
