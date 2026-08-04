"""Resolve effective TTS voice ID from persona and voice bundle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from loguru import Logger

    from app.models.database import Persona, VoiceBundle


def resolve_effective_tts_voice_id(
    *,
    persona: "Persona | None",
    voice_bundle: "VoiceBundle | None",
    default_voice: str | None = None,
) -> str | None:
    """Prefer persona voice when set, else voice bundle, else provider default."""
    if persona and persona.tts_voice_id:
        return persona.tts_voice_id
    if voice_bundle:
        return getattr(voice_bundle, "tts_voice", None) or default_voice
    return default_voice


def log_effective_tts_voice(
    logger: "Logger",
    *,
    path_name: str,
    persona: "Persona | None",
    voice_bundle: "VoiceBundle | None",
    resolved_voice_id: str | None,
) -> None:
    """Log when persona voice overrides the voice bundle default."""
    if not persona or not persona.tts_voice_id:
        return
    bundle_voice = getattr(voice_bundle, "tts_voice", None) if voice_bundle else None
    if bundle_voice == persona.tts_voice_id:
        return
    logger.info(
        "[{}] Using persona TTS voice {} (persona={}, bundle voice={})",
        path_name,
        persona.tts_voice_id,
        persona.id,
        bundle_voice,
    )
