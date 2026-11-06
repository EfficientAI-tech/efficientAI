"""Harbor scoring respects agent scope (AND with scenario)."""

from app.models.database import Agent, EvaluatorResult, Metric
from app.models.enums import EvaluatorResultStatus
from app.services.harbor.trial_store import score_trial
from app.services.metrics.evaluation_scope import replace_metric_agents


def test_score_trial_skips_criteria_for_other_agent(db_session, sim_rows, monkeypatch):
    other_agent = Agent(
        organization_id=sim_rows.agent.organization_id,
        workspace_id=sim_rows.agent.workspace_id,
        name="Other agent",
    )
    agent_only = Metric(
        organization_id=sim_rows.metric.organization_id,
        workspace_id=sim_rows.metric.workspace_id,
        name="Other agent only",
        description="Wrong agent",
        metric_type="boolean",
    )
    db_session.add_all([other_agent, agent_only])
    db_session.flush()
    replace_metric_agents(
        db_session,
        organization_id=sim_rows.metric.organization_id,
        metric=agent_only,
        agent_ids=[other_agent.id],
    )
    sim_rows.run.metric_ids = [str(sim_rows.metric.id), str(agent_only.id)]
    sim_rows.run.metric_success_criteria = [
        {"metric_id": str(sim_rows.metric.id), "kind": "rating", "op": "gte", "threshold": 0.7},
        {"metric_id": str(agent_only.id), "kind": "boolean", "success_when": "yes"},
    ]
    db_session.add(
        EvaluatorResult(
            result_id="900001",
            organization_id=sim_rows.run.organization_id,
            workspace_id=sim_rows.run.workspace_id,
            agent_id=sim_rows.agent.id,
            scenario_id=sim_rows.scenario.id,
            persona_id=sim_rows.persona.id,
            simulation_run_id=sim_rows.run.id,
            harbor_trial_name="refund__abc123",
            status=EvaluatorResultStatus.EVALUATING.value,
            transcription="Agent: hello\nCustomer: hi",
        )
    )
    db_session.commit()

    def _fake_eval(db, *, result, agent, persona, scenario, metric_ids=None):
        return {
            str(sim_rows.metric.id): {
                "value": 0.9,
                "type": "rating",
                "metric_name": sim_rows.metric.name,
            }
        }, [sim_rows.metric]

    monkeypatch.setattr(
        "app.workers.tasks.process_evaluator_result.evaluate_transcript_metrics", _fake_eval
    )
    _rewards, details = score_trial(
        db_session,
        simulation_run_id=sim_rows.run.id,
        trial_name="refund__abc123",
        pass_threshold=0.7,
    )
    assert details["passed"] is True
    assert str(agent_only.id) not in (details.get("metric_scores") or {})
