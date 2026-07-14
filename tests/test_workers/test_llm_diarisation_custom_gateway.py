"""Tests for custom gateway LLM support in LLM-only diarisation."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.workers.tasks.helpers import llm_diarisation


def test_custom_gateway_audio_allowed_requires_gateway_model(monkeypatch):
    org_id = uuid4()
    fake_row = SimpleNamespace(
        id=uuid4(),
        routing_mode="gateway",
        gateway_model="production-gpt4",
    )

    monkeypatch.setattr(
        "app.services.credentials.resolve_ai_provider",
        lambda *args, **kwargs: fake_row,
    )

    assert llm_diarisation._custom_gateway_audio_allowed(
        provider_value="custom",
        organization_id=org_id,
        db=SimpleNamespace(),
    )


def test_custom_gateway_audio_rejected_without_gateway_model(monkeypatch):
    org_id = uuid4()
    fake_row = SimpleNamespace(
        id=uuid4(),
        routing_mode="gateway",
        gateway_model="",
    )

    monkeypatch.setattr(
        "app.services.credentials.resolve_ai_provider",
        lambda *args, **kwargs: fake_row,
    )

    assert not llm_diarisation._custom_gateway_audio_allowed(
        provider_value="custom",
        organization_id=org_id,
        db=SimpleNamespace(),
    )


def test_custom_gateway_audio_allowed_with_gateway_model_even_when_direct(
    monkeypatch,
):
    org_id = uuid4()
    fake_row = SimpleNamespace(
        id=uuid4(),
        routing_mode="direct",
        gateway_model="production-gpt4",
    )

    monkeypatch.setattr(
        "app.services.credentials.resolve_ai_provider",
        lambda *args, **kwargs: fake_row,
    )

    assert llm_diarisation._custom_gateway_audio_allowed(
        provider_value="custom",
        organization_id=org_id,
        db=SimpleNamespace(),
    )


def test_diarize_audio_rejects_custom_without_gateway(monkeypatch):
    monkeypatch.setattr(
        "app.services.credentials.resolve_ai_provider",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(llm_diarisation.LLMDiarisationError) as exc_info:
        llm_diarisation.diarize_audio_with_llm(
            b"\x00" * 1024,
            llm_provider="custom",
            llm_model="ignored",
            organization_id=uuid4(),
            db=SimpleNamespace(),
            mime_type="audio/wav",
        )

    assert "not supported" in str(exc_info.value).lower()


def test_diarize_audio_accepts_custom_gateway_provider(monkeypatch):
    org_id = uuid4()
    fake_row = SimpleNamespace(
        id=uuid4(),
        routing_mode="gateway",
        gateway_model="production-gpt4",
    )

    monkeypatch.setattr(
        "app.services.credentials.resolve_ai_provider",
        lambda *args, **kwargs: fake_row,
    )
    monkeypatch.setattr(
        "app.services.ai.llm_gateway.resolve_effective_routing",
        lambda *args, **kwargs: (None, "bifrost"),
    )
    monkeypatch.setattr(
        llm_diarisation,
        "_generate_diarisation_response",
        lambda **kwargs: {
            "text": '{"turns": [{"speaker": "agent", "text": "Hello"}]}'
        },
    )

    turns = llm_diarisation.diarize_audio_with_llm(
        b"\x00" * 1024,
        llm_provider="custom",
        llm_model="ignored",
        organization_id=org_id,
        db=SimpleNamespace(),
        mime_type="audio/wav",
    )

    assert len(turns) == 1
    assert turns[0]["text"] == "Hello"
