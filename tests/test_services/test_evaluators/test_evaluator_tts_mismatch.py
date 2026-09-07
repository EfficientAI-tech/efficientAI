"""Tests for agent/persona TTS provider mismatch helpers."""

import pytest
from fastapi import HTTPException

from app.models.database import EvaluatorResult
from app.services.evaluators.evaluator_helpers import (
    agent_persona_tts_mismatch,
    require_matching_agent_persona_tts,
    validate_agent_persona_tts,
)
from app.services.evaluators.evaluator_phone_run_service import initiate_phone_evaluator_call


def test_agent_persona_tts_mismatch_none_when_providers_match(db_session, make_agent, make_persona, make_voice_bundle):
    bundle = make_voice_bundle(tts_provider="openai")
    agent = make_agent(voice_bundle_id=bundle.id)
    persona = make_persona(tts_provider="openai")

    assert agent_persona_tts_mismatch(db_session, agent, persona) is None


def test_agent_persona_tts_mismatch_detects_difference(db_session, make_agent, make_persona, make_voice_bundle):
    bundle = make_voice_bundle(tts_provider="voicemaker")
    agent = make_agent(voice_bundle_id=bundle.id)
    persona = make_persona(tts_provider="openai", name="Stale Persona")

    mismatch = agent_persona_tts_mismatch(db_session, agent, persona)
    assert mismatch is not None
    assert mismatch.persona_name == "Stale Persona"
    assert mismatch.persona_provider == "openai"
    assert mismatch.bundle_provider == "voicemaker"


def test_validate_agent_persona_tts_raises_on_mismatch(db_session, make_agent, make_persona, make_voice_bundle):
    bundle = make_voice_bundle(tts_provider="openai")
    agent = make_agent(voice_bundle_id=bundle.id)
    persona = make_persona(tts_provider="elevenlabs")

    with pytest.raises(HTTPException) as exc:
        validate_agent_persona_tts(db_session, agent, persona)
    assert exc.value.status_code == 400
    assert "must match the agent's voice bundle" in exc.value.detail


def test_require_matching_agent_persona_tts_run_message(db_session, make_agent, make_persona, make_voice_bundle):
    bundle = make_voice_bundle(tts_provider="voicemaker")
    agent = make_agent(voice_bundle_id=bundle.id)
    persona = make_persona(tts_provider="openai", name="Caller")

    with pytest.raises(HTTPException) as exc:
        require_matching_agent_persona_tts(db_session, agent, persona)
    assert exc.value.status_code == 400
    assert "voice bundle changed to 'voicemaker'" in exc.value.detail
    assert "Edit the evaluator" in exc.value.detail


def test_initiate_phone_evaluator_call_rejects_mismatch_without_result_row(
    db_session,
    org_id,
    default_workspace,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_voice_bundle,
):
    bundle = make_voice_bundle(tts_provider="voicemaker")
    agent = make_agent(voice_bundle_id=bundle.id)
    persona = make_persona(tts_provider="openai")
    scenario = make_scenario(agent_id=agent.id)
    evaluator = make_evaluator(agent_id=agent.id, persona_id=persona.id, scenario_id=scenario.id)

    before = db_session.query(EvaluatorResult).count()
    with pytest.raises(HTTPException) as exc:
        initiate_phone_evaluator_call(
            db_session,
            org_id,
            default_workspace.id,
            evaluator,
            agent,
            "+15551234567",
        )
    after = db_session.query(EvaluatorResult).count()

    assert exc.value.status_code == 400
    assert before == after
