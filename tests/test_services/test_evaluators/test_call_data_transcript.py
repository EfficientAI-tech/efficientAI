"""Tests for call_data transcript extraction."""

from app.services.evaluators.call_data_transcript import extract_transcript_from_call_data


def test_vapi_extracts_transcript_from_messages_when_transcript_field_empty():
    call_data = {
        "transcript": "",
        "endedReason": "call.in-progress.error-assistant-did-not-receive-customer-audio",
        "messages": [
            {"role": "assistant", "message": "Hello, how can I help?"},
            {"role": "user", "message": "Hi there"},
        ],
    }
    text, segments = extract_transcript_from_call_data(call_data, "vapi")
    assert "Hello, how can I help?" in text
    assert "Hi there" in text
    assert len(segments) == 2


def test_hydrate_helper_permanent_vapi_reason():
    from app.workers.tasks import process_evaluator_result as task_module

    class _Result:
        audio_s3_key = None
        transcription = None
        provider_platform = "vapi"
        call_data = {
            "endedReason": "call.in-progress.error-assistant-did-not-receive-customer-audio",
        }

    msg = task_module._permanent_input_failure_message(_Result(), db=None)
    assert msg is not None
    assert "microphone" in msg.lower()
