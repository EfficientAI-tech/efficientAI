"""Tests for persona TTS config validation."""

import pytest

from app.services.personas.persona_tts_config import (
    normalize_persona_tts_config,
    validate_persona_tts_config,
)


def test_validate_elevenlabs_speed_range():
    validate_persona_tts_config("elevenlabs", {"speed": 1.0, "stability": 0.5})
    with pytest.raises(ValueError, match="speed"):
        validate_persona_tts_config("elevenlabs", {"speed": 5.0})


def test_validate_rejects_unknown_keys():
    with pytest.raises(ValueError, match="Unsupported tts_config keys"):
        validate_persona_tts_config("openai", {"stability": 0.5})


def test_normalize_cartesia_generation_config():
    normalized = normalize_persona_tts_config(
        "cartesia",
        {"generation_config_speed": 1.1, "generation_config_emotion": "excited"},
    )
    assert normalized == {"generation_config": {"speed": 1.1, "emotion": "excited"}}


def test_validate_requires_provider_when_config_present():
    with pytest.raises(ValueError, match="requires tts_provider"):
        validate_persona_tts_config(None, {"speed": 1.0})
