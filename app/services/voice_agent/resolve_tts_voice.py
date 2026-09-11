"""Resolve effective TTS voice ID from persona and voice bundle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from loguru import Logger

    from app.models.database import Persona, VoiceBundle


def _normalize_tts_provider(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value).lower()
    return str(value).lower()


def persona_bundle_tts_providers_mismatch(
    persona: "Persona | None",
    voice_bundle: "VoiceBundle | None",
) -> bool:
    """True when both providers are set and differ (case-insensitive)."""
    if persona is None or voice_bundle is None:
        return False
    persona_provider = _normalize_tts_provider(getattr(persona, "tts_provider", None))
    bundle_provider = _normalize_tts_provider(getattr(voice_bundle, "tts_provider", None))
    if not persona_provider or not bundle_provider:
        return False
    return persona_provider != bundle_provider


def resolve_effective_tts_voice_id(
    *,
    persona: "Persona | None",
    voice_bundle: "VoiceBundle | None",
    default_voice: str | None = None,
    allow_persona_voice: bool = True,
) -> str | None:
    """Prefer persona voice when set, else voice bundle, else provider default."""
    if allow_persona_voice and persona and persona.tts_voice_id:
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
    allow_persona_voice: bool = True,
) -> None:
    """Log when persona voice overrides the voice bundle default or is skipped."""
    if persona and not allow_persona_voice and persona.tts_voice_id:
        logger.info(
            "[{}] Ignoring persona TTS voice {} due to provider mismatch (persona={}, bundle provider={})",
            path_name,
            persona.tts_voice_id,
            persona.id,
            getattr(voice_bundle, "tts_provider", None) if voice_bundle else None,
        )
        return
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
