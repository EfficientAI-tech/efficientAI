"""Trial conversation + scoring against the DB, with LLM calls faked."""

import json

import pytest

import app.services.agents.chat_production_leg as prod_mod
import app.services.testing.llm_to_llm_evaluator_simulation as sim_mod
from app.models.database import EvaluatorResult
from app.models.enums import EvaluatorResultStatus
from app.services.harbor.trial_store import TrialRefs, run_trial_conversation, score_trial


@pytest.fixture
def fake_llms(monkeypatch):
    replies = iter(
        [
            "Hi, I'm sorry your order was late. Can I have the order number?",
            "It's 4411. I want my money back.",
            "Done, the refund is on its way. Goodbye!",
        ]
    )

    def _fake_generate(**_kwargs):
        return {"text": next(replies)}

    monkeypatch.setattr(sim_mod.llm_service, "generate_response", _fake_generate)
    monkeypatch.setattr(prod_mod.llm_service, "generate_response", _fake_generate)
    monkeypatch.setattr(
        "app.services.knowledge_bases.retrieval.agent_has_ready_knowledge", lambda *a, **k: False
    )


def _refs(sim_rows, trial_name="refund__abc123"):
    return TrialRefs(
        simulation_run_id=sim_rows.run.id,
        scenario_id=sim_rows.scenario.id,
        persona_id=sim_rows.persona.id,
        trial_name=trial_name,
    )


def test_run_trial_conversation_records_result_and_trajectory(
    db_session, sim_rows, fake_llms, tmp_path
):
    trajectory_path = tmp_path / "agent" / "trajectory.json"
    outcome = run_trial_conversation(
        db_session,
        refs=_refs(sim_rows),
        trajectory_path=trajectory_path,
        production_override=None,
        test_override=None,
    )

    result = db_session.query(EvaluatorResult).filter_by(harbor_trial_name="refund__abc123").one()
    assert outcome["evaluator_result_id"] == str(result.id)
    assert result.simulation_run_id == sim_rows.run.id
    assert result.status == EvaluatorResultStatus.EVALUATING.value
    # The test agent opens (persona opener, no LLM call), then the legs alternate.
    assert [s["speaker"] for s in result.speaker_segments] == [
        "Speaker 1",
        "Speaker 2",
        "Speaker 1",
        "Speaker 2",
    ]
    assert result.call_data["partial"] is False
    assert result.call_data["harbor_trial_name"] == "refund__abc123"

    trajectory = json.loads(trajectory_path.read_text())
    assert [s["source"] for s in trajectory["steps"]] == [
        "system",
        "user",
        "agent",
        "user",
        "agent",
    ]
    assert [s["step_id"] for s in trajectory["steps"]] == [1, 2, 3, 4, 5]

    validator_mod = pytest.importorskip("harbor.utils.trajectory_validator")
    validator = validator_mod.TrajectoryValidator()
    assert validator.validate(trajectory), validator.get_errors()


def test_retry_reuses_result_row(db_session, sim_rows, fake_llms, tmp_path, monkeypatch):
    run_trial_conversation(
        db_session,
        refs=_refs(sim_rows),
        trajectory_path=tmp_path / "t.json",
        production_override=None,
        test_override=None,
    )
    monkeypatch.setattr(
        sim_mod.llm_service, "generate_response", lambda **_: {"text": "Bye now, goodbye!"}
    )
    monkeypatch.setattr(
        prod_mod.llm_service,
        "generate_response",
        lambda **_: {"text": "Hello there, how can I help?"},
    )
    run_trial_conversation(
        db_session,
        refs=_refs(sim_rows),
        trajectory_path=tmp_path / "t.json",
        production_override=None,
        test_override=None,
    )
    assert (
        db_session.query(EvaluatorResult).filter_by(simulation_run_id=sim_rows.run.id).count() == 1
    )


def test_production_failure_marks_trial_failed(
    db_session, sim_rows, fake_llms, tmp_path, monkeypatch
):
    def _boom(**_):
        raise RuntimeError("provider down")

    monkeypatch.setattr(prod_mod.llm_service, "generate_response", _boom)
    with pytest.raises(Exception, match="provider down"):
        run_trial_conversation(
            db_session,
            refs=_refs(sim_rows),
            trajectory_path=tmp_path / "t.json",
            production_override=None,
            test_override=None,
        )
    result = db_session.query(EvaluatorResult).filter_by(simulation_run_id=sim_rows.run.id).one()
    assert result.status == EvaluatorResultStatus.FAILED.value
    assert "provider down" in result.error_message


@pytest.mark.parametrize("empathy,passed", [(0.9, True), (0.4, False)])
def test_score_trial_sets_reward_and_pass_legacy_threshold(
    db_session, sim_rows, fake_llms, tmp_path, monkeypatch, empathy, passed
):
    run_trial_conversation(
        db_session,
        refs=_refs(sim_rows),
        trajectory_path=tmp_path / "t.json",
        production_override=None,
        test_override=None,
    )
    metric = sim_rows.metric

    def _fake_eval(db, *, result, agent, persona, scenario, metric_ids=None):
        return {str(metric.id): {"value": empathy, "type": "rating", "metric_name": metric.name}}, [
            metric
        ]

    monkeypatch.setattr(
        "app.workers.tasks.process_evaluator_result.evaluate_transcript_metrics", _fake_eval
    )
    rewards, details = score_trial(
        db_session,
        simulation_run_id=sim_rows.run.id,
        trial_name="refund__abc123",
        pass_threshold=0.7,
    )

    assert rewards == {"reward": empathy, "empathy": empathy}
    assert details["passed"] is passed
    result = db_session.query(EvaluatorResult).filter_by(simulation_run_id=sim_rows.run.id).one()
    assert result.status == EvaluatorResultStatus.COMPLETED.value
    assert result.reward == empathy
    assert result.passed is passed


def test_score_trial_with_success_criteria(
    db_session, sim_rows, fake_llms, tmp_path, monkeypatch
):
    metric = sim_rows.metric
    sim_rows.run.metric_success_criteria = [
        {
            "metric_id": str(metric.id),
            "kind": "rating",
            "op": "gte",
            "threshold": 0.7,
        }
    ]
    db_session.commit()
    run_trial_conversation(
        db_session,
        refs=_refs(sim_rows),
        trajectory_path=tmp_path / "t2.json",
        production_override=None,
        test_override=None,
    )

    def _fake_eval(db, *, result, agent, persona, scenario, metric_ids=None):
        return {str(metric.id): {"value": 0.4, "type": "rating", "metric_name": metric.name}}, [
            metric
        ]

    monkeypatch.setattr(
        "app.workers.tasks.process_evaluator_result.evaluate_transcript_metrics", _fake_eval
    )
    rewards, details = score_trial(
        db_session,
        simulation_run_id=sim_rows.run.id,
        trial_name="refund__abc123",
        pass_threshold=0.7,
    )
    assert details["passed"] is False
    assert rewards["reward"] == 0.0
    result = db_session.query(EvaluatorResult).filter_by(simulation_run_id=sim_rows.run.id).one()
    assert result.passed is False
    assert result.reward == 0.0


def test_score_trial_without_transcript_raises(db_session, sim_rows):
    with pytest.raises(ValueError, match="No transcript"):
        score_trial(
            db_session, simulation_run_id=sim_rows.run.id, trial_name="missing", pass_threshold=0.7
        )
