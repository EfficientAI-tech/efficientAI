"""Tests for empty/single-speaker transcript guards in transcribe worker."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


def _load_transcribe_module():
    """Load transcribe module without pulling app.workers.tasks __init__."""
    module_name = "transcribe_call_import_row_isolated"
    if module_name in sys.modules:
        return sys.modules[module_name]

    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "app" / "workers" / "tasks" / "transcribe_call_import_row.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def transcribe_module():
    return _load_transcribe_module()


def test_plain_text_from_turns_joins_single_speaker_content(transcribe_module):
    turns = [
        {"speaker": "agent", "text": "hello there"},
        {"speaker": "agent", "text": "how are you"},
    ]
    assert (
        transcribe_module._plain_text_from_turns(turns)
        == "hello there how are you"
    )


def test_single_speaker_transcript_resolution_never_none(transcribe_module):
    turns = transcribe_module._segments_to_user_agent_turns(
        [
            {
                "speaker": "Speaker 1",
                "text": "hello only one voice",
                "start": 0.0,
                "end": 1.0,
            }
        ]
    )
    rendered_turns = ""
    plain_text = None
    transcript_to_store = (
        rendered_turns
        or plain_text
        or transcribe_module._plain_text_from_turns(turns)
        or ""
    ).strip()
    assert transcript_to_store == "hello only one voice"
    assert len(transcript_to_store) == len("hello only one voice")
