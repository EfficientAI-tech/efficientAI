"""Tests for caller opening text and persona name injection."""

from app.services.testing.test_agent_template import (
    TestAgentFirstMessage,
    CALLER_MODE_SPEAK_FIRST,
    CALLER_MODE_WAIT,
    ensure_opening_includes_persona_name,
    resolve_caller_opening_text,
)


def test_ensure_opening_includes_persona_name_when_missing():
    assert ensure_opening_includes_persona_name(
        "Hi, I need help with a bill.",
        "Alex",
    ) == "Hi, this is Alex. Hi, I need help with a bill."


def test_ensure_opening_includes_persona_name_when_present():
    assert ensure_opening_includes_persona_name(
        "Hi, this is Alex. I need help.",
        "Alex",
    ) == "Hi, this is Alex. I need help."


def test_resolve_caller_opening_text_injects_persona_into_scenario_line():
    opening = resolve_caller_opening_text(
        first_message=TestAgentFirstMessage(caller_mode=CALLER_MODE_SPEAK_FIRST),
        persona_name="Alex",
        scenario_first_message="Hi, I need help with a bill.",
    )
    assert opening is not None
    assert "Alex" in opening
    assert "bill" in opening


def test_resolve_caller_opening_text_injects_persona_into_template_line():
    opening = resolve_caller_opening_text(
        first_message=TestAgentFirstMessage(
            caller_mode=CALLER_MODE_SPEAK_FIRST,
            caller_message="Hello, I'm calling because I need some help.",
        ),
        persona_name="Alex",
    )
    assert opening is not None
    assert "Alex" in opening


def test_resolve_caller_opening_text_none_when_caller_waits():
    assert resolve_caller_opening_text(
        first_message=TestAgentFirstMessage(caller_mode=CALLER_MODE_WAIT),
        persona_name="Alex",
    ) is None
