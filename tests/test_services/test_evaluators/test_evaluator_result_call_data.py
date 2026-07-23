"""Tests for evaluator result call_data slimming."""

from app.services.evaluators.evaluator_result_call_data import slim_call_data_for_evaluator_result


def test_slim_call_data_drops_transcript_duplicates():
    raw = {
        "call_ref": "abc",
        "from_number": "+1",
        "live_transcript": [{"role": "user", "content": "hi"}],
        "messages": [{"role": "user", "content": "hi"}],
        "transcript": "user: hi",
        "last_event": {"Event": "Hangup"},
    }
    slim = slim_call_data_for_evaluator_result(raw)
    assert slim["call_ref"] == "abc"
    assert "live_transcript" not in slim
    assert "messages" not in slim
    assert "transcript" not in slim
    assert slim["last_event"]["Event"] == "Hangup"


def test_slim_call_data_strips_generated_call_analysis_duplicate():
    raw = {
        "call_analysis": {"call_successful": True},
        "generated": {"call_analysis": {"call_successful": True}, "other": 1},
    }
    slim = slim_call_data_for_evaluator_result(raw)
    assert slim["call_analysis"]["call_successful"] is True
    assert slim["generated"] == {"other": 1}
