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
