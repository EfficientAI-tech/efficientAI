"""Batch Sarvam TTS: Bulbul v4 Flash uses convert_stream."""

import sys
import types
from unittest.mock import MagicMock

import pytest

from efficientai.services.sarvam.http_tts import synthesize_sarvam_bytes


def test_bulbul_v4_flash_uses_convert_stream(monkeypatch):
    captured: dict = {}

    class _TTS:
        def convert_stream(self, **kwargs):
            captured.update(kwargs)
            return [b"chunk1", b"chunk2"]

    client = types.SimpleNamespace(text_to_speech=_TTS())
    mock_ctor = MagicMock(return_value=client)
    fake_sarvamai = types.ModuleType("sarvamai")
    fake_sarvamai.SarvamAI = mock_ctor
    monkeypatch.setitem(sys.modules, "sarvamai", fake_sarvamai)

    audio, ttfb_ms = synthesize_sarvam_bytes(
        "hello",
        "bulbul:v4-flash",
        "key",
        voice="shubh_enhi_ads",
        config={"pace": 1.2, "target_language_code": "hi-IN"},
    )

    assert audio == b"chunk1chunk2"
    assert ttfb_ms >= 0
    mock_ctor.assert_called_once_with(api_subscription_key="key")
    assert captured["model"] == "bulbul:v4-flash"
    assert captured["speaker"] == "shubh_enhi_ads"
    assert captured["language_code"] == "hi-IN"
    assert captured["speech_sample_rate"] == 24000
    assert captured["output_audio_codec"] == "wav"
    assert captured["pace"] == 1.2


def test_bulbul_v4_flash_accepts_single_bytes_response(monkeypatch):
    class _TTS:
        def convert_stream(self, **_kwargs):
            return b"whole-file"

    client = types.SimpleNamespace(text_to_speech=_TTS())
    fake_sarvamai = types.ModuleType("sarvamai")
    fake_sarvamai.SarvamAI = lambda **_kw: client
    monkeypatch.setitem(sys.modules, "sarvamai", fake_sarvamai)

    audio, _ = synthesize_sarvam_bytes("hi", "bulbul:v4-flash", "key")
    assert audio == b"whole-file"


def test_bulbul_v3_still_uses_rest_json(monkeypatch):
    captured: dict = {}

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"audios": ["YQ=="]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return _Response()

    monkeypatch.setattr(
        "efficientai.services.sarvam.http_tts.requests.post",
        fake_post,
    )

    synthesize_sarvam_bytes("hello", "bulbul:v3", "key", voice="ritu")

    assert captured["json"]["model"] == "bulbul:v3"
    assert captured["json"]["speaker"] == "ritu"