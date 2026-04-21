"""Helper tests for process_evaluator_result task module."""

import importlib.util
from pathlib import Path

_TASK_PATH = Path(__file__).resolve().parents[2] / "app" / "workers" / "tasks" / "process_evaluator_result.py"
_TASK_SPEC = importlib.util.spec_from_file_location("process_evaluator_result_under_test", _TASK_PATH)
process_evaluator_result = importlib.util.module_from_spec(_TASK_SPEC)
assert _TASK_SPEC is not None and _TASK_SPEC.loader is not None
_TASK_SPEC.loader.exec_module(process_evaluator_result)


def test_extract_audio_url_supports_smallest_recordings():
    call_data = {"recording_url": "https://audio.smallest.ai/call.wav"}
    audio_url = process_evaluator_result._extract_audio_url(call_data, "smallest")

    assert audio_url == "https://audio.smallest.ai/call.wav"
"""Unit tests for process_evaluator_result helper utilities."""


def test_extract_audio_url_supports_smallest_recordings():
    import importlib

    task_module = importlib.import_module("app.workers.tasks.process_evaluator_result")

    call_data = {"recording_url": "https://audio.smallest.ai/call.wav"}

    assert task_module._extract_audio_url(call_data, "smallest") == "https://audio.smallest.ai/call.wav"
