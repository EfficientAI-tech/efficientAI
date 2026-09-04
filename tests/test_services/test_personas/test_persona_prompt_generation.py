"""Tests for persona prompt generation."""

from types import SimpleNamespace

import pytest

from app.services.personas.persona_prompt_generation import generate_persona_prompt_from_agent


def test_generate_from_test_agent_fails_when_prompt_missing():
    agent = SimpleNamespace(
        name="Support Bot",
        description="",
        provider_prompt="Production prompt only",
    )

    with pytest.raises(ValueError, match="no test agent prompt"):
        generate_persona_prompt_from_agent(
            agent,
            source="test_agent",
            persona_name=None,
            persona_gender=None,
            additional_context=None,
            llm_provider=None,  # type: ignore[arg-type]
            llm_model="gpt-4o-mini",
            organization_id=None,  # type: ignore[arg-type]
            db=None,  # type: ignore[arg-type]
        )
