from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.enums import ModelProvider
from app.services.testing.llm_to_llm_evaluator_simulation import (
    run_llm_to_llm_evaluator_simulation,
)


def test_run_llm_to_llm_evaluator_simulation_builds_transcript(monkeypatch):
    org_id = uuid4()
    agent_id = uuid4()
    evaluator_id = uuid4()
    persona_id = uuid4()
    scenario_id = uuid4()
    result_id = uuid4()
    bundle_id = uuid4()

    responses = iter(
        [
            {"text": "Hi, how can I help you today?"},
            {"text": "I need help with my order."},
            {"text": "Sure, what is your order number?"},
            {"text": "Thanks, goodbye."},
        ]
    )

    def _fake_generate(**_kwargs):
        return next(responses)

    import app.services.testing.llm_to_llm_evaluator_simulation as sim_mod

    monkeypatch.setattr(sim_mod.llm_service, "generate_response", _fake_generate)

    evaluator = SimpleNamespace(
        id=evaluator_id,
        evaluator_id="ev-1",
        workspace_id=uuid4(),
    )
    agent = SimpleNamespace(
        id=agent_id,
        name="Support Bot",
        voice_bundle_id=bundle_id,
        description="You help customers with orders.",
        provider_prompt=None,
    )
    persona = SimpleNamespace(
        id=persona_id,
        name="Alex",
        description="Impatient customer",
        gender=None,
        max_turns=4,
        tts_provider=None,
        tts_voice_name=None,
        tts_voice_id=None,
    )
    scenario = SimpleNamespace(
        id=scenario_id,
        name="Order status",
        description="Check an order",
        required_info={"goal": "Get order status"},
    )
    result = SimpleNamespace(
        id=result_id,
        result_id="res-1",
        transcription=None,
        speaker_segments=None,
        provider_platform=None,
        call_data=None,
        duration_seconds=None,
    )
    voice_bundle = SimpleNamespace(
        id=bundle_id,
        llm_provider=ModelProvider.OPENAI,
        llm_model="gpt-4o-mini",
        llm_config=None,
        llm_credential_id=None,
    )
    db = SimpleNamespace()

    def _query(model):
        class _Q:
            def filter(self, *_args, **_kwargs):
                return self

            def first(self):
                if model.__name__ == "VoiceBundle":
                    return voice_bundle
                return None

        return _Q()

    db.query = _query

    output = run_llm_to_llm_evaluator_simulation(
        evaluator=evaluator,
        result=result,
        agent=agent,
        persona=persona,
        scenario=scenario,
        organization_id=org_id,
        db=db,
    )

    assert output["provider_platform"] == "internal"
    assert result.provider_platform == "internal"
    assert "Speaker 1:" in result.transcription
    assert "Speaker 2:" in result.transcription
    assert result.call_data["source"] == "llm_to_llm_simulation"
