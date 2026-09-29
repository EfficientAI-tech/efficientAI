from types import SimpleNamespace
from uuid import uuid4

from app.models.enums import CallMediumEnum
from app.services.agents.chat_llm_config import (
    agent_has_chat_simulation_config,
    should_use_llm_text_simulation,
)
from app.services.testing.llm_to_llm_evaluator_simulation import (
    _build_eval_user_opener,
    _production_turn_needs_user_seed,
    _should_end_conversation,
)
from app.services.testing.test_agent_template import derive_caller_first_message


def test_voice_agent_with_bundle_does_not_use_chat_simulation_config():
    agent = SimpleNamespace(
        call_medium=CallMediumEnum.PHONE_CALL.value,
        voice_bundle_id=uuid4(),
        main_llm_provider="openai",
        main_llm_model="gpt-4.1-nano",
        chat_connection_type=None,
        voice_ai_integration_id=None,
        voice_ai_agent_id=None,
        provider_prompt="",
        description="",
        chat_connection_config={},
    )
    assert agent_has_chat_simulation_config(agent) is False


def test_voice_agent_with_bundle_and_integration_uses_bridge_not_text_sim():
    agent = SimpleNamespace(
        call_medium=CallMediumEnum.PHONE_CALL.value,
        voice_bundle_id=uuid4(),
        voice_ai_integration_id=uuid4(),
        voice_ai_agent_id="asst-1",
        main_llm_provider="openai",
        main_llm_model="gpt-4.1-nano",
    )
    use_sim = should_use_llm_text_simulation(
        agent,
        has_voice_bundle=True,
        has_voice_ai_integration=True,
    )
    assert use_sim is False


def test_goodbye_detection_ignores_mid_conversation_thank_you():
    text = "Thank you, can I get your order number?"
    assert _should_end_conversation(text, turn_index=4) is False


def test_goodbye_detection_closing_thank_you():
    assert _should_end_conversation("Thank you.", turn_index=4) is True


def test_production_turn_needs_user_seed_when_transcript_empty():
    assert _production_turn_needs_user_seed([]) is True


def test_build_eval_user_opener_when_caller_waits_for_provider_style_chat():
    agent = SimpleNamespace(call_medium=CallMediumEnum.CHAT.value)
    persona = SimpleNamespace(name="Alex")
    first = derive_caller_first_message("assistant_speaks_first")
    text = _build_eval_user_opener(
        agent=agent,
        persona=persona,
        first_message_config=first,
        scenario_first_message=None,
    )
    assert "Alex" in text
    assert text.strip()
