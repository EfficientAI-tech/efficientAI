from app.services.testing.chat_prompt_adaptation import adapt_production_prompt_for_chat_simulation
from app.services.testing.test_agent_simulation_prompt import production_prompt_for_simulation
from types import SimpleNamespace


def test_adapt_production_prompt_includes_chat_mode_preamble():
    out = adapt_production_prompt_for_chat_simulation("You are a voice assistant on the phone.")
    assert "Text chat mode" in out
    assert "voice assistant on the phone" in out


def test_chat_agent_production_prompt_for_simulation_is_adapted():
    agent = SimpleNamespace(
        call_medium="chat",
        description="",
        provider_prompt="Thank you for calling Wellness Partners.",
    )
    prompt = production_prompt_for_simulation(agent)
    assert "Text chat mode" in prompt
    assert "Thank you for calling" in prompt
