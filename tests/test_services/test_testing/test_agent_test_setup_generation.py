"""Tests for agent test setup generation service."""

import pytest

from app.services.testing.agent_test_setup_generation import (
    AgentTestPromptSection,
    CANONICAL_SECTION_KEYS,
    _normalize_scenario_drafts,
    _normalize_sections,
    assemble_test_agent_prompt,
)


def test_assemble_test_agent_prompt_orders_canonical_sections():
    sections = [
        AgentTestPromptSection(key="constraints", title="Constraints", content="Never share PII."),
        AgentTestPromptSection(key="purpose", title="Purpose", content="Handle refunds."),
    ]
    assembled = assemble_test_agent_prompt(sections)
    assert assembled.index("## Purpose") < assembled.index("## Constraints")
    assert "Handle refunds." in assembled
    assert "Never share PII." in assembled


def test_normalize_sections_fills_missing_keys():
    raw = [
        {"key": "purpose", "title": "Purpose", "content": "Support agent."},
        {"key": "behavior", "title": "Behavior", "content": "Answer questions."},
    ]
    sections = _normalize_sections(raw)
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
