"""Tests for test agent template helpers."""

import pytest

from app.services.testing.test_agent_template import (
    CANONICAL_SECTION_KEYS,
    CALLER_MODE_SPEAK_FIRST,
    CALLER_MODE_WAIT,
    PRODUCTION_MODE_ASSISTANT_SPEAKS_FIRST,
    PRODUCTION_MODE_ASSISTANT_WAITS,
    TestAgentPromptSection,
    assemble_test_agent_prompt,
    derive_caller_first_message,
    normalize_first_message,
    normalize_sections,
    resolve_caller_opening_text,
    should_caller_speak_first,
)


def test_assemble_test_agent_prompt_orders_canonical_sections():
    sections = [
        TestAgentPromptSection(key="constraints", title="Constraints", content="Never share PII."),
        TestAgentPromptSection(
            key="complementary_goal", title="Role and Goal", content="Book an appointment."
        ),
    ]
    assembled = assemble_test_agent_prompt(sections)
    assert assembled.index("## Role and Goal") < assembled.index("## Constraints")
    assert "Book an appointment." in assembled
    assert "Never share PII." in assembled


def test_normalize_sections_fills_missing_keys():
    raw = [
        {"key": "complementary_goal", "title": "Role and Goal", "content": "Support caller."},
        {"key": "talking_style", "title": "Talking Style", "content": "Speak naturally."},
    ]
    sections = normalize_sections(raw)
    assert [s.key for s in sections] == list(CANONICAL_SECTION_KEYS)
    assert sections[0].content == "Support caller."
    assert sections[-1].key == "constraints"
    assert "Not specified" in sections[-1].content


def test_derive_caller_first_message_inverts_production_speaks_first():
    result = derive_caller_first_message(
        PRODUCTION_MODE_ASSISTANT_SPEAKS_FIRST,
        "Thank you for calling Wellness Partners.",
    )
    assert result.caller_mode == CALLER_MODE_WAIT
    assert result.production_message == "Thank you for calling Wellness Partners."
    assert result.caller_message is None


def test_derive_caller_first_message_inverts_production_waits():
    result = derive_caller_first_message(PRODUCTION_MODE_ASSISTANT_WAITS)
    assert result.caller_mode == CALLER_MODE_SPEAK_FIRST
    assert result.caller_message is not None


def test_resolve_caller_opening_text_prefers_scenario_override():
    first_message = derive_caller_first_message(PRODUCTION_MODE_ASSISTANT_WAITS)
    opening = resolve_caller_opening_text(
        first_message=first_message,
        persona_name="Alex",
        scenario_first_message="Hi, I need help with my bill.",
    )
    assert opening == "Hi, I need help with my bill."


def test_should_caller_speak_first():
    wait = derive_caller_first_message(PRODUCTION_MODE_ASSISTANT_SPEAKS_FIRST, "Hello")
    speak = derive_caller_first_message(PRODUCTION_MODE_ASSISTANT_WAITS)
    assert should_caller_speak_first(wait) is False
    assert should_caller_speak_first(speak) is True


def test_normalize_first_message_invalid_mode_defaults():
    result = normalize_first_message({"production_mode": "invalid"})
    assert result.production_mode == PRODUCTION_MODE_ASSISTANT_WAITS
