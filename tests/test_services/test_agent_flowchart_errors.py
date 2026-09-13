from app.services.agent_flowchart import _is_unsupported_temperature_error
from app.workers.tasks.agent_flowchart_jobs import _user_facing_flowchart_error


def test_is_unsupported_temperature_error():
    exc = RuntimeError(
        "LLM generation failed for openai/gpt-4.1: "
        "Error code: 400 - temperature does not support 0.0 value"
    )
    assert _is_unsupported_temperature_error(exc) is True
    assert _is_unsupported_temperature_error(RuntimeError("timeout")) is False


def test_user_facing_flowchart_error_strips_traceback():
    exc = RuntimeError(
        "LLM generation failed for openai/gpt-4.1: Error code: 400 - bad request\n"
        "Details: Traceback (most recent call last):\n"
        '  File "litellm/openai.py", line 1\n'
    )
    message = _user_facing_flowchart_error(exc)
    assert "Traceback" not in message
    assert "Details:" not in message
    assert "bad request" in message
