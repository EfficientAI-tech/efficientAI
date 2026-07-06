from app.services.imported_agent_constants import (
    AGENT_PROVIDER_PROMPT_TAG_PREFIX,
    AGENT_SYSTEM_PROMPT_TAG_PREFIX,
    IMPORTED_AGENT_TAG,
    partial_supports_flowchart,
)


def test_partial_supports_flowchart_imported_agent():
    assert partial_supports_flowchart([IMPORTED_AGENT_TAG]) is True


def test_partial_supports_flowchart_test_agent_prompt():
    tag = f"{AGENT_SYSTEM_PROMPT_TAG_PREFIX}abc-123"
    assert partial_supports_flowchart(["agents", tag]) is True


def test_partial_supports_flowchart_voice_ai_prompt():
    tag = f"{AGENT_PROVIDER_PROMPT_TAG_PREFIX}abc-123"
    assert partial_supports_flowchart([tag]) is True


def test_partial_supports_flowchart_regular_partial():
    assert partial_supports_flowchart(["agents", "system-prompt"]) is False
    assert partial_supports_flowchart(None) is False
