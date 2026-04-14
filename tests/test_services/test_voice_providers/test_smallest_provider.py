"""Tests for Smallest voice provider adapter."""

import pytest
import requests

from app.services.voice_providers import smallest as smallest_module
from app.services.voice_providers.smallest import SmallestVoiceProvider


def test_create_web_call_starts_webcall_without_phone_number(monkeypatch):
    provider = SmallestVoiceProvider(api_key="key")
    calls = {}

    def _fake_request(method, path, **kwargs):
        calls["method"] = method
        calls["path"] = path
        calls["kwargs"] = kwargs
        return {
            "token": "token-123",
            "host": "wss://atoms.example.livekit.cloud",
            "roomName": "room-123",
            "conversationId": "conv-123",
            "callId": "CALL-123",
        }

    monkeypatch.setattr(provider, "_request", _fake_request)

    result = provider.create_web_call(agent_id="agent-1", metadata={"foo": "bar"})

    assert calls["method"] == "POST"
    assert calls["path"] == "/conversation/webcall"
    assert calls["kwargs"]["json"]["agentId"] == "agent-1"
    assert result["call_id"] == "CALL-123"
    assert result["access_token"] == "token-123"
    assert result["host"] == "wss://atoms.example.livekit.cloud"


def test_create_web_call_uses_outbound_when_phone_number_present(monkeypatch):
    provider = SmallestVoiceProvider(api_key="key")
    calls = {}

    def _fake_request(method, path, **kwargs):
        calls["method"] = method
        calls["path"] = path
        calls["kwargs"] = kwargs
        return {"conversationId": "conv-outbound-1"}

    monkeypatch.setattr(provider, "_request", _fake_request)

    result = provider.create_web_call(agent_id="agent-1", phone_number="+1234567890")

    assert calls["method"] == "POST"
    assert calls["path"] == "/conversation/outbound"
    assert calls["kwargs"]["json"]["phoneNumber"] == "+1234567890"
    assert result["call_id"] == "conv-outbound-1"


def test_retrieve_call_metrics_normalizes_transcript_segments(monkeypatch):
    provider = SmallestVoiceProvider(api_key="key")
    payload = {
        "conversationId": "conv-1",
        "status": "completed",
        "duration": 8.2,
        "startedAt": "2026-04-13T10:00:00Z",
        "recordingUrl": "https://audio.example/call.wav",
        "transcript": [
            {"role": "user", "text": "hello", "timeInCallSecs": 0.5},
            {"role": "agent", "text": "hi there", "timeInCallSecs": 1.3},
        ],
    }
    monkeypatch.setattr(provider, "_get_conversation", lambda _call_id: payload)

    metrics = provider.retrieve_call_metrics("conv-1")

    assert metrics["call_id"] == "conv-1"
    assert metrics["call_status"] == "ended"
    assert metrics["duration_seconds"] == 8.2
    assert metrics["recording_url"] == "https://audio.example/call.wav"
    assert metrics["transcript"].startswith("User: hello")
    assert len(metrics["transcript_object"]) == 2


def test_extract_agent_prompt_prefers_global_prompt(monkeypatch):
    provider = SmallestVoiceProvider(api_key="key")
    monkeypatch.setattr(
        provider,
        "get_agent",
        lambda _agent_id: {"globalPrompt": "System instructions", "prompt": "fallback"},
    )

    assert provider.extract_agent_prompt("agent-1") == "System instructions"


def test_request_retries_without_proxy_on_proxy_error(monkeypatch):
    provider = SmallestVoiceProvider(api_key="key")
    calls = {"request": 0, "session_request": 0, "trust_env_values": []}

    def _request_via_env_proxy(**_kwargs):
        calls["request"] += 1
        raise requests.exceptions.ProxyError("Tunnel connection failed: 403 Forbidden")

    class _Response:
        ok = True
        content = b"{}"

        @staticmethod
        def json():
            return {"email": "owner@smallest.ai"}

    class _Session:
        def __init__(self):
            self._trust_env = True

        @property
        def trust_env(self):
            return self._trust_env

        @trust_env.setter
        def trust_env(self, value):
            calls["trust_env_values"].append(value)
            self._trust_env = value

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, **_kwargs):
            calls["session_request"] += 1
            return _Response()

    monkeypatch.setattr(smallest_module.requests, "request", _request_via_env_proxy)
    monkeypatch.setattr(smallest_module.requests, "Session", _Session)

    payload = provider.get_user_details()

    assert payload["email"] == "owner@smallest.ai"
    assert calls["request"] == 1
    assert calls["session_request"] == 1
    assert False in calls["trust_env_values"]
