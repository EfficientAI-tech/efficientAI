"""Tests for pure helper behavior in provider classes."""

import json
from pathlib import Path

from app.services.voice_providers.elevenlabs import ElevenLabsVoiceProvider
from app.services.voice_providers.retell import RetellVoiceProvider
from app.services.voice_providers.vapi import VapiVoiceProvider

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "elevenlabs"


def test_strip_code_fences_handles_complete_and_partial_blocks():
    provider = ElevenLabsVoiceProvider(api_key="k")

    full = "```markdown\nHello world\n```"
    partial = "```text\nHello world"
    plain = "Hello world"

    assert provider._strip_code_fences(full) == "Hello world"
    assert provider._strip_code_fences(partial) == "Hello world"
    assert provider._strip_code_fences(plain) == "Hello world"


def test_vapi_make_json_serializable_converts_nested_values():
    provider = VapiVoiceProvider(api_key="k")
    payload = {"outer": [{"num": 1, "flag": True}, {"text": "ok"}]}
    result = provider._make_json_serializable(payload)

    assert result == payload


def test_elevenlabs_list_agents_normalizes_response(monkeypatch):
    fixture = json.loads((FIXTURE_DIR / "agents_list.json").read_text())

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return fixture

    monkeypatch.setattr(
        "app.services.voice_providers.elevenlabs.requests.get",
        lambda *_args, **_kwargs: _Resp(),
    )

    provider = ElevenLabsVoiceProvider(api_key="k")
    payload = provider.list_agents(page_size=10)
    assert payload["has_more"] is False
    assert payload["agents"][0]["id"].startswith("agent_")
    assert payload["agents"][0]["name"] == "Customer Support Agent"


def test_elevenlabs_retrieve_conversation_trace_returns_payload(monkeypatch):
    fixture = json.loads((FIXTURE_DIR / "conv_otel.json").read_text())

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return fixture

    monkeypatch.setattr(
        "app.services.voice_providers.elevenlabs.requests.get",
        lambda *_args, **_kwargs: _Resp(),
    )

    provider = ElevenLabsVoiceProvider(api_key="k")
    payload = provider.retrieve_conversation_trace("conv_123")
    assert payload["conversation_id"] == fixture["conversation_id"]
    assert "otlp_traces" in payload


def test_vapi_list_agents_normalizes_response(monkeypatch):
    fixture = {
        "assistants": [
            {
                "id": "assist_abc",
                "name": "Vapi Support Agent",
                "isArchived": False,
                "createdAt": "2026-02-02T10:00:00.000Z",
            }
        ],
        "has_more": False,
        "next_cursor": None,
    }

    class _Resp:
        ok = True
        status_code = 200

        def json(self):
            return fixture

    monkeypatch.setattr(
        "app.services.voice_providers.vapi.requests.get",
        lambda *_args, **_kwargs: _Resp(),
    )

    provider = VapiVoiceProvider(api_key="k")
    payload = provider.list_agents(page_size=10)
    assert payload["has_more"] is False
    assert payload["agents"][0]["id"] == "assist_abc"
    assert payload["agents"][0]["name"] == "Vapi Support Agent"


def test_retell_list_agents_normalizes_response(monkeypatch):
    provider = RetellVoiceProvider(api_key="k")

    class _Response:
        def model_dump(self):
            return {
                "items": [
                    {
                        "agent_id": "agent_retell_123",
                        "agent_name": "Retell Support Agent",
                        "is_archived": False,
                        "created_at": "2026-01-02T00:00:00.000Z",
                    }
                ]
            }

    class _AgentApi:
        @staticmethod
        def list():
            return _Response()

    monkeypatch.setattr(provider, "client", type("C", (), {"agent": _AgentApi()})())
    payload = provider.list_agents(page_size=10)
    assert payload["agents"][0]["id"] == "agent_retell_123"
    assert payload["agents"][0]["name"] == "Retell Support Agent"


def test_retell_extract_agent_prompt_prefers_inline_response_engine_prompt(monkeypatch):
    provider = RetellVoiceProvider(api_key="k")

    class _AgentApi:
        @staticmethod
        def retrieve(agent_id):
            del agent_id
            return {
                "agent_id": "agent_retell_123",
                "response_engine": {"type": "retell-llm", "general_prompt": "Inline general prompt"},
            }

    monkeypatch.setattr(provider, "client", type("C", (), {"agent": _AgentApi()})())
    assert provider.extract_agent_prompt("agent_retell_123") == "Inline general prompt"


def test_retell_extract_agent_prompt_handles_llm_lookup_error_with_fallback(monkeypatch):
    provider = RetellVoiceProvider(api_key="k")

    class _AgentApi:
        @staticmethod
        def retrieve(agent_id):
            del agent_id
            return {
                "agent_id": "agent_retell_123",
                "response_engine": {
                    "type": "retell-llm",
                    "llm_id": "llm_123",
                    "system_prompt": "Fallback system prompt",
                },
            }

    class _LlmApi:
        @staticmethod
        def retrieve(llm_id):
            raise RuntimeError(f"failed to read llm {llm_id}")

    monkeypatch.setattr(provider, "client", type("C", (), {"agent": _AgentApi(), "llm": _LlmApi()})())
    assert provider.extract_agent_prompt("agent_retell_123") == "Fallback system prompt"


def test_retell_extract_agent_prompt_reads_camel_case_llm_prompt(monkeypatch):
    provider = RetellVoiceProvider(api_key="k")

    class _AgentApi:
        @staticmethod
        def retrieve(agent_id):
            del agent_id
            return {
                "agent_id": "agent_retell_123",
                "response_engine": {"type": "retell-llm", "llm_id": "llm_123"},
            }

    class _LlmApi:
        @staticmethod
        def retrieve(llm_id):
            del llm_id
            return {
                "settings": {
                    "systemPrompt": "Prompt from camelCase settings",
                }
            }

    monkeypatch.setattr(provider, "client", type("C", (), {"agent": _AgentApi(), "llm": _LlmApi()})())
    assert provider.extract_agent_prompt("agent_retell_123") == "Prompt from camelCase settings"
