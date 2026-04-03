"""Unit tests for Pydantic schema validation logic."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    AgentCreate,
    AgentResponse,
    EvaluationCreate,
    VoiceBundleResponse,
)


def test_evaluation_create_accepts_allowed_metrics():
    payload = EvaluationCreate(
        audio_id=uuid4(),
        evaluation_type="asr",
        metrics=["wer", "latency"],
    )

    assert payload.metrics == ["wer", "latency"]


def test_evaluation_create_rejects_unknown_metric():
    with pytest.raises(ValidationError, match="Invalid metrics"):
        EvaluationCreate(
            audio_id=uuid4(),
            evaluation_type="asr",
            metrics=["wer", "not_real_metric"],
        )


def test_agent_create_requires_phone_number_for_phone_call():
    with pytest.raises(ValidationError, match="phone_number is required"):
        AgentCreate(
            name="Support Agent",
            description="This description has enough words to satisfy minimum word count requirement.",
            call_type="outbound",
            call_medium="phone_call",
            voice_ai_integration_id=uuid4(),
            voice_ai_agent_id="agent_1",
        )


def test_agent_response_converts_legacy_enum_strings():
    response = AgentResponse(
        id=uuid4(),
        name="Agent",
        phone_number="+1234567890",
        language="ENGLISH",
        description="ok",
        call_type="OUTBOUND",
        call_medium="PHONE_CALL",
        voice_bundle_id=None,
        ai_provider_id=None,
        voice_ai_integration_id=uuid4(),
        voice_ai_agent_id="agent_123",
        provider_prompt=None,
        provider_prompt_synced_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert response.language.value == "en"
    assert response.call_type.value == "outbound"
    assert response.call_medium.value == "phone_call"


def test_voice_bundle_response_converts_provider_enum_from_uppercase_name():
    now = datetime.now(UTC)
    response = VoiceBundleResponse(
        id=uuid4(),
        name="Bundle A",
        description=None,
        bundle_type="stt_llm_tts",
        stt_provider="OPENAI",
        stt_model="gpt-4o-mini-transcribe",
        llm_provider="ANTHROPIC",
        llm_model="claude-3-5-sonnet",
        llm_temperature=0.7,
        llm_max_tokens=256,
        llm_config=None,
        tts_provider="ELEVENLABS",
        tts_model="eleven_multilingual_v2",
        tts_voice="voice_1",
        tts_config=None,
        s2s_provider=None,
        s2s_model=None,
        s2s_config=None,
        extra_metadata=None,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=None,
    )

    assert response.bundle_type.value == "stt_llm_tts"
    assert response.stt_provider.value == "openai"
    assert response.llm_provider.value == "anthropic"
    assert response.tts_provider.value == "elevenlabs"
