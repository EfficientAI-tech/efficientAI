"""Unit tests for process_evaluator_result helper utilities."""

import importlib
from types import SimpleNamespace
from uuid import uuid4


def _task_module():
    return importlib.import_module("app.workers.tasks.process_evaluator_result")


def test_extract_audio_url_supports_smallest_recordings():
    task_module = _task_module()
    call_data = {"recording_url": "https://audio.smallest.ai/call.wav"}
    assert task_module._extract_audio_url(call_data, "smallest") == "https://audio.smallest.ai/call.wav"


def test_should_record_external_agent_call_usage_only_for_provider_calls():
    task_module = _task_module()
    agent_id = uuid4()

    external = SimpleNamespace(agent_id=agent_id, provider_platform="vapi")
    internal = SimpleNamespace(agent_id=agent_id, provider_platform=None)
    simulation = SimpleNamespace(agent_id=agent_id, provider_platform="")
    no_agent = SimpleNamespace(agent_id=None, provider_platform="vapi")

    assert task_module._should_record_external_agent_call_usage(external) is True
    assert task_module._should_record_external_agent_call_usage(internal) is False
    assert task_module._should_record_external_agent_call_usage(simulation) is False
    assert task_module._should_record_external_agent_call_usage(no_agent) is False


def test_resolve_call_duration_seconds_prefers_result_field():
    task_module = _task_module()
    result = SimpleNamespace(duration_seconds=12.4, call_data={})
    assert task_module._resolve_call_duration_seconds(result) == 13

