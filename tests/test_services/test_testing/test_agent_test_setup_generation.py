"""Tests for agent test setup generation service."""

import json

import pytest

from app.services.testing.agent_test_setup_generation import (
    AgentTestPromptSection,
    CANONICAL_SECTION_KEYS,
    _normalize_scenario_drafts,
    _parse_generation_payload,
    _strip_llm_text_wrapper,
    assemble_test_agent_prompt,
)
from app.services.testing.test_agent_template import normalize_sections


def test_strip_llm_text_wrapper_removes_markdown_fences():
    wrapped = "```json\n{\"sections\": []}\n```"
    assert _strip_llm_text_wrapper(wrapped).startswith("{")


def test_strip_llm_text_wrapper_preserves_plain_text():
    plain = "You are a caller interacting with a support agent."
    assert _strip_llm_text_wrapper(plain) == plain


def test_assemble_test_agent_prompt_orders_canonical_sections():
    sections = [
        AgentTestPromptSection(key="constraints", title="Constraints", content="Never share PII."),
        AgentTestPromptSection(
            key="complementary_goal", title="Role and Goal", content="Handle refunds."
        ),
    ]
    assembled = assemble_test_agent_prompt(sections)
    assert assembled.index("## Role and Goal") < assembled.index("## Constraints")
    assert "Handle refunds." in assembled
    assert "Never share PII." in assembled


def test_parse_generation_payload_returns_sections_and_first_message():
    payload = {
        "sections": [
            {"key": "complementary_goal", "title": "Role and Goal", "content": "Get help."},
            {"key": "talking_style", "title": "Talking Style", "content": "Be polite."},
            {"key": "questions_to_ask", "title": "Questions to Ask", "content": "Ask about status."},
            {"key": "information_to_relay", "title": "Information to Relay", "content": "Account number."},
            {"key": "constraints", "title": "Constraints", "content": "Stay realistic."},
        ],
        "first_message": {
            "production_mode": "assistant_speaks_first",
            "production_message": "Thank you for calling.",
        },
    }
    sections, first_message = _parse_generation_payload(json.dumps(payload))
    assert len(sections) == len(CANONICAL_SECTION_KEYS)
    assert first_message.caller_mode == "wait"
    assert first_message.production_message == "Thank you for calling."


def test_normalize_sections_fills_missing_keys():
    raw = [
        {"key": "complementary_goal", "title": "Role and Goal", "content": "Support agent."},
        {"key": "talking_style", "title": "Talking Style", "content": "Answer questions."},
    ]
    sections = normalize_sections(raw)
    assert [s.key for s in sections] == list(CANONICAL_SECTION_KEYS)
    assert sections[0].content == "Support agent."
    assert sections[-1].key == "constraints"
    assert "Not specified" in sections[-1].content


def test_normalize_scenario_drafts_requires_name_and_description():
    drafts = _normalize_scenario_drafts(
        [
            {"name": "Refund happy path", "description": "Caller requests refund.", "goal": "Get refund"},
            {"name": "", "description": "skip"},
        ]
    )
    assert len(drafts) == 1
    assert drafts[0].name == "Refund happy path"
    assert drafts[0].goal == "Get refund"


def test_normalize_scenario_drafts_raises_when_empty():
    with pytest.raises(ValueError, match="valid scenario drafts"):
        _normalize_scenario_drafts([])
