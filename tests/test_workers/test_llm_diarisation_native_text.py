"""Native-script diariser output is opt-in and never required to parse."""

from types import SimpleNamespace
from uuid import uuid4

from app.workers.tasks.helpers.llm_diarisation import (
    DEFAULT_DIARIZATION_PROMPT,
    _estimate_diarisation_max_tokens,
    _parse_turns_from_response,
    diarize_transcript_with_llm,
)
from app.workers.tasks.helpers.script_enforcement import find_violating_turns


def test_parser_accepts_text_native_and_aliases():
    response = {
        "text": (
            '{"turns": ['
            '{"speaker": "agent", "text": "Hello", "text_native": "Hello"},'
            '{"speaker": "user", "text": "Main", "native": "मैं"}'
            "]}"
        ),
        "truncated": False,
    }
    turns = _parse_turns_from_response(response)
    assert turns[0]["text_native"] == "Hello"
    assert turns[1]["text_native"] == "मैं"


def test_parser_tolerates_missing_text_native():
    response = {
        "text": '{"turns": [{"speaker": "agent", "text": "Hello"}]}',
        "truncated": False,
    }
    turns = _parse_turns_from_response(response)
    assert "text_native" not in turns[0]
    assert turns[0]["text"] == "Hello"


def test_text_native_indic_is_not_a_script_violation():
    turns = [
        {
            "speaker": "agent",
            "text": "Main aap ki",
            "text_native": "मैं आपकी",
        }
    ]
    assert find_violating_turns(turns) == []


def test_omitted_flag_uses_today_prompt_and_budget(monkeypatch):
    captured: dict = {}

    def _fake_generate_response(**kwargs):
        captured["messages"] = kwargs["messages"]
        captured["max_tokens"] = kwargs["task_defaults"]["max_tokens"]
        return {"text": '{"turns": [{"speaker": "agent", "text": "Hi"}]}'}

    monkeypatch.setattr(
        "app.workers.tasks.helpers.llm_diarisation.llm_service.generate_response",
        _fake_generate_response,
    )
    diarize_transcript_with_llm(
        "Hi there",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        organization_id=uuid4(),
        db=SimpleNamespace(),
    )
    assert captured["messages"][0]["content"] == DEFAULT_DIARIZATION_PROMPT
    assert captured["max_tokens"] == _estimate_diarisation_max_tokens(
        text_length=len("Hi there")
    )


def test_truncated_native_response_retries_without_native_emission(monkeypatch):
    prompts: list[str] = []

    def _fake_generate_response(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        if len(prompts) == 1:
            return {"text": '{"turns": [{"speaker": "agent", "text": "partial', "truncated": True}
        return {
            "text": '{"turns": [{"speaker": "agent", "text": "Done"}]}',
            "truncated": False,
        }

    monkeypatch.setattr(
        "app.workers.tasks.helpers.llm_diarisation.llm_service.generate_response",
        _fake_generate_response,
    )
    turns = diarize_transcript_with_llm(
        "Hi there",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        organization_id=uuid4(),
        db=SimpleNamespace(),
        emit_native_text=True,
    )
    assert "text_native" in prompts[0]
    assert prompts[1] == DEFAULT_DIARIZATION_PROMPT
    assert turns[0]["text"] == "Done"
