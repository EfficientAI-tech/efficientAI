"""Tests for OpenRouter Jev System One routing helpers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "app" / "services" / "ai" / "openrouter_jev.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("openrouter_jev", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_is_openrouter_jev_model():
    mod = _load_module()
    assert mod.is_openrouter_jev_model("openrouter", "typesafe/jev-1.13") is True
    assert mod.is_openrouter_jev_model("openai", "typesafe/jev-1.13") is False
    assert mod.is_openrouter_jev_model("openrouter", "openai/gpt-4o") is False


def test_normalize_openrouter_jev_model_id():
    mod = _load_module()
    assert mod.normalize_openrouter_jev_model_id("typesafe/jev-1.13") == "typesafe/jev-1.13"
    assert (
        mod.normalize_openrouter_jev_model_id("openrouter/typesafe/jev-1.13")
        == "typesafe/jev-1.13"
    )


def test_extract_jev_payload_from_user_json():
    mod = _load_module()
    payload = {"state": "hello", "questions": {"q1": {"type": "noul"}}}
    messages = [{"role": "user", "content": json.dumps(payload)}]
    state, questions = mod.extract_jev_payload(messages, None)
    assert state == "hello"
    assert "q1" in questions


def test_extract_jev_payload_from_response_format():
    mod = _load_module()
    messages = [{"role": "user", "content": "transcript text"}]
    extra = {
        "response_format": {
            "type": "questions",
            "questions": {"noul": {"type": "noul"}},
        }
    }
    state, questions = mod.extract_jev_payload(messages, extra)
    assert state == "transcript text"
    assert "noul" in questions


def test_systemone_response_to_text():
    mod = _load_module()
    text = mod.systemone_response_to_text(
        {"answers": {"q1": {"type": "noul", "noul": 0.9}}}
    )
    parsed = json.loads(text)
    assert parsed["answers"]["q1"]["noul"] == 0.9


def test_call_systemone_preserves_gateway_authorization_header():
    mod = _load_module()
    captured = {}

    class _Response:
        def read(self):
            return b'{"answers": {}}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout=120.0):
        captured["headers"] = dict(request.header_items())
        return _Response()

    import urllib.request

    original = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        mod.call_systemone(
            url="http://gateway/typesafe/v1/systemone",
            api_key="sk-provider-key",
            model_id="jev-1.13.0",
            state="s",
            questions={"q": {"type": "noul"}},
            extra_headers={"Authorization": "Bearer gateway-vk"},
        )
    finally:
        urllib.request.urlopen = original

    assert captured["headers"]["Authorization"] == "Bearer gateway-vk"


def test_call_systemone_sets_authorization_when_only_non_auth_extra_headers():
    mod = _load_module()
    captured = {}

    class _Response:
        def read(self):
            return b'{"answers": {}}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout=120.0):
        captured["headers"] = dict(request.header_items())
        return _Response()

    import urllib.request

    original = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        mod.call_systemone(
            url="http://gateway/typesafe/v1/systemone",
            api_key="sk-provider-key",
            model_id="jev-1.13.0",
            state="s",
            questions={"q": {"type": "noul"}},
            extra_headers={"x-bf-vk": "gateway-vk"},
        )
    finally:
        urllib.request.urlopen = original

    assert captured["headers"]["Authorization"] == "Bearer sk-provider-key"
    assert captured["headers"]["X-bf-vk"] == "gateway-vk"
