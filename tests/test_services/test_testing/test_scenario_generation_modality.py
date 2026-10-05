from app.services.testing.scenario_generation_modality import (
    build_scenario_generation_requirements,
    generate_scenarios_system_prompt,
    scenario_modality_from_call_medium,
)


def test_scenario_modality_from_call_medium():
    assert scenario_modality_from_call_medium("chat") == "chat"
    assert scenario_modality_from_call_medium("phone_call") == "voice"


def test_chat_scenario_requirements_use_customer_language():
    text = build_scenario_generation_requirements("chat")
    assert "Customer intent" in text
    assert "TEXT CHAT" in text
    assert "not caller" in text.lower()
    assert "Caller intent" not in text


def test_voice_scenario_requirements_use_caller_language():
    text = build_scenario_generation_requirements("voice")
    assert "Caller intent" in text
    assert "Customer intent" not in text


def test_chat_system_prompt_forbids_caller_wording():
    prompt = generate_scenarios_system_prompt("chat")
    assert "text chat" in prompt.lower()
    assert "never caller" in prompt.lower()
