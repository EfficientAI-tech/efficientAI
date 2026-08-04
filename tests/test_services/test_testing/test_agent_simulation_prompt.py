"""Tests for test_agent_simulation_prompt helpers."""

from types import SimpleNamespace
from uuid import uuid4

from app.services.testing.test_agent_simulation_prompt import (
    SCENARIO_REFERENCE_HEADING,
    compose_test_agent_simulation_prompt,
    format_persona_block,
    format_scenarios_reference_appendix,
    get_agent_base_prompt,
    merge_generated_description_with_scenario_appendix,
    build_test_agent_system_prompt,
    build_persona_description_for_bridge,
    resolve_persona_max_turns,
    scenario_reference_token,
)


def _agent(**kwargs):
    defaults = {"name": "Support Bot", "description": "Handle support calls.", "provider_prompt": "Provider prompt."}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _scenario(**kwargs):
    defaults = {
        "id": uuid4(),
        "name": "Billing dispute",
        "description": "User disputes a charge.",
        "required_info": {"goal": "Get refund status", "first_message": "Hi, I need help with a bill."},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _persona(**kwargs):
    defaults = {
        "name": "Alex",
        "gender": "female",
        "tts_provider": "cartesia",
        "tts_voice_name": "Sarah",
        "tts_voice_id": "voice-1",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_get_agent_base_prompt_prefers_description():
    assert get_agent_base_prompt(_agent()) == "Handle support calls."


def test_get_agent_base_prompt_falls_back_to_provider_prompt():
    agent = _agent(description="", provider_prompt="Synced.")
    assert get_agent_base_prompt(agent) == "Synced."


def test_compose_test_agent_simulation_prompt_includes_agent_and_scenario():
    text = compose_test_agent_simulation_prompt(_agent(), _scenario())
    assert "Agent system prompt:" in text
    assert "Handle support calls." in text
    assert "Billing dispute" in text
    assert "Get refund status" in text


def test_format_persona_block_includes_traits():
    block = format_persona_block(_persona(), persona_description="A frustrated customer")
    assert "Name: Alex" in block
    assert "Gender: female" in block
    assert "Voice: Sarah" in block
    assert "Description: A frustrated customer" in block


def test_build_test_agent_system_prompt_has_three_sections():
    prompt = build_test_agent_system_prompt(_agent(), _persona(), _scenario(), max_turns=5)
    assert "TEST AGENT SIMULATION PROMPT" in prompt
    assert "PERSONA" in prompt
    assert "INSTRUCTIONS:" in prompt
    assert "After 5 exchanges" in prompt
    assert "Handle support calls." in prompt
    assert "Name: Alex" in prompt


def test_merge_scenario_appendix_replaces_existing_section():
    base = f"# Agent\n\nSome text.\n\n{SCENARIO_REFERENCE_HEADING}\n\n### Old\nold"
    appendix = format_scenarios_reference_appendix([_scenario(name="New", description="New desc")])
    merged = merge_generated_description_with_scenario_appendix(base, appendix)
    assert "Old" not in merged
    assert "New desc" in merged
    assert "@scenario{" in merged


def test_get_agent_base_prompt_strips_scenario_reference_appendix():
    appendix = format_scenarios_reference_appendix([_scenario()])
    agent = _agent(description=f"Core prompt only.\n\n{appendix}")
    assert get_agent_base_prompt(agent) == "Core prompt only."


def test_scenario_reference_token_uses_uuid():
    scenario = _scenario()
    scenario.id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert scenario_reference_token(scenario) == "@scenario{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}"


def test_format_scenarios_reference_appendix_empty():
    assert format_scenarios_reference_appendix([]) == ""


def test_build_persona_description_prefers_stored_description():
    persona = _persona(description="An impatient billing caller")
    assert build_persona_description_for_bridge(persona) == "An impatient billing caller"


def test_resolve_persona_max_turns_uses_persona_value():
    persona = _persona(max_turns=8)
    assert resolve_persona_max_turns(persona) == 8
    assert resolve_persona_max_turns(_persona()) == 20


def test_build_test_agent_system_prompt_uses_persona_max_turns():
    prompt = build_test_agent_system_prompt(_agent(), _persona(max_turns=3), _scenario())
    assert "After 3 exchanges" in prompt
