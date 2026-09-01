"""Unit tests for evaluator-result metric cluster adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.models.database import EvaluatorResult, Metric
from app.models.enums import EvaluatorResultStatus
from app.models.schemas import MetricFailurePolicy
from app.services.call_import_metric_clusters import (
    _build_flagged_row_payload_from_source,
    build_metric_cluster_progress,
)
from app.services.metric_cluster_rows import (
    build_evaluator_results_scope_key,
    evaluator_result_to_cluster_row,
)


def _seed_clusterable_evaluator_result(
    db_session,
    *,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_evaluator_result,
    make_metric,
):
    from app.models.database import EvaluatorSuite

    agent = make_agent(name="Cluster Scope Agent")
    persona = make_persona()
    scenario = make_scenario(agent_id=agent.id, name="Scope Scenario")
    suite = EvaluatorSuite(
        organization_id=agent.organization_id,
        workspace_id=agent.workspace_id,
        name="Scope Suite",
        agent_id=agent.id,
        persona_id=persona.id,
    )
    db_session.add(suite)
    db_session.commit()
    db_session.refresh(suite)

    metric = make_metric(name="Pass/Fail", metric_type="boolean")
    evaluator = make_evaluator(
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        suite_id=suite.id,
    )
    result = make_evaluator_result(
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        status="completed",
        metric_scores={
            str(metric.id): {
                "value": False,
                "type": "boolean",
                "metric_name": "Pass/Fail",
                "rationale": "Failed to confirm identity.",
            }
        },
    )
    return agent, scenario, result, metric


def test_evaluator_result_to_cluster_row_payload():
    metric_id = uuid4()
    metric = Metric(
        id=metric_id,
        organization_id=uuid4(),
        workspace_id=uuid4(),
        name="Pass/Fail",
        metric_type="boolean",
        enabled=True,
    )
    result = EvaluatorResult(
        id=uuid4(),
        result_id="661122",
        organization_id=uuid4(),
        workspace_id=uuid4(),
        status=EvaluatorResultStatus.COMPLETED.value,
        transcription="User: hello\nBot: hi",
        metric_scores={
            str(metric_id): {
                "value": False,
                "type": "boolean",
                "metric_name": "Pass/Fail",
                "rationale": "Bot failed to confirm identity.",
            }
        },
    )
    source = evaluator_result_to_cluster_row(result)
    policy = MetricFailurePolicy(metric_id=str(metric_id), failure_values=["false"])
    payload = _build_flagged_row_payload_from_source(source, metric, policy)
    assert payload is not None
    assert payload["conversation_id"] == "661122"
    assert payload["rationale"] == "Bot failed to confirm identity."
    assert "hello" in payload["transcript"]


def test_build_evaluator_results_scope_key_includes_dates_and_scenarios():
    agent_id = uuid4()
    scenario_a = uuid4()
    scenario_b = uuid4()
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    until = datetime(2026, 1, 31, tzinfo=timezone.utc)

    key_a = build_evaluator_results_scope_key(
        agent_id=agent_id,
        scenario_ids=[scenario_b, scenario_a],
        since=since,
        until=until,
    )
    key_b = build_evaluator_results_scope_key(
        agent_id=agent_id,
        scenario_ids=[scenario_a, scenario_b],
        since=since,
        until=until,
    )
    assert key_a == key_b
    assert str(agent_id) in key_a
    assert str(scenario_a) in key_a
    assert "since:2026-01-01" in key_a
    assert "until:2026-01-31" in key_a

    different_dates = build_evaluator_results_scope_key(
        agent_id=agent_id,
        scenario_ids=[scenario_a],
        since=datetime(2026, 2, 1, tzinfo=timezone.utc),
        until=until,
    )
    assert different_dates != key_a


def test_build_metric_cluster_progress_includes_selected_call_fields():
    payload = build_metric_cluster_progress(
        completed_llm_calls=2,
        total_llm_calls=10,
        completed_selected_calls=5,
        total_selected_calls=20,
        current_metric_name="Pass/Fail",
        current_metric_index=1,
        total_metrics=3,
    )
    assert payload["completed_selected_calls"] == 5
    assert payload["total_selected_calls"] == 20
    assert payload["current_metric_name"] == "Pass/Fail"
    assert payload["current_metric_index"] == 1
    assert payload["total_metrics"] == 3


def test_build_generation_scope_snapshot_resolves_agent_and_scenario_names(
    db_session,
    org_id,
    default_workspace,
    make_agent,
    make_scenario,
):
    from app.models.database import EvaluatorResultClusterJob
    from app.services.evaluators.evaluator_result_metric_clusters import (
        build_generation_scope_snapshot,
    )

    agent = make_agent(name="Scope Agent")
    scenario = make_scenario(agent_id=agent.id, name="Billing Flow")

    job = EvaluatorResultClusterJob(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        scope_key="agent:test",
        agent_id=agent.id,
        scenario_ids=[str(scenario.id)],
    )
    db_session.add(job)
    db_session.commit()

    snapshot = build_generation_scope_snapshot(
        db_session,
        job=job,
        eligible_call_count=10,
        selected_call_count=3,
    )
    assert snapshot["agent_name"] == "Scope Agent"
    assert snapshot["scenario_names"] == ["Billing Flow"]
    assert snapshot["eligible_call_count"] == 10
    assert snapshot["selected_call_count"] == 3


def test_count_completed_evaluator_results_for_job(
    db_session,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_evaluator_result,
    make_metric,
):
    from app.services.evaluators.evaluator_result_metric_clusters import (
        count_completed_evaluator_results_for_job,
        get_or_create_cluster_job,
    )

    agent, scenario, _result, _metric = _seed_clusterable_evaluator_result(
        db_session,
        make_agent=make_agent,
        make_persona=make_persona,
        make_scenario=make_scenario,
        make_evaluator=make_evaluator,
        make_evaluator_result=make_evaluator_result,
        make_metric=make_metric,
    )
    job = get_or_create_cluster_job(
        db_session,
        organization_id=agent.organization_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        scenario_ids=[scenario.id],
    )
    assert count_completed_evaluator_results_for_job(db_session, job) == 1


def test_is_cluster_job_stale_when_completed_rows_advance(
    db_session,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_evaluator_result,
    make_metric,
):
    from app.models.database import EvaluatorSuite
    from app.services.evaluators.evaluator_result_metric_clusters import (
        get_or_create_cluster_job,
        is_cluster_job_stale,
    )

    agent, scenario, result, metric = _seed_clusterable_evaluator_result(
        db_session,
        make_agent=make_agent,
        make_persona=make_persona,
        make_scenario=make_scenario,
        make_evaluator=make_evaluator,
        make_evaluator_result=make_evaluator_result,
        make_metric=make_metric,
    )
    job = get_or_create_cluster_job(
        db_session,
        organization_id=agent.organization_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        scenario_ids=[scenario.id],
    )
    job.metric_clusters = {
        "status": "completed",
        "groups": [{"metric_id": "m1", "metric_name": "Pass/Fail", "clusters": []}],
        "discovered_problems": [],
        "generated_at_completed_rows": 1,
    }
    db_session.commit()
    assert is_cluster_job_stale(db_session, job) is False

    suite = EvaluatorSuite(
        organization_id=agent.organization_id,
        workspace_id=agent.workspace_id,
        name="Extra Suite",
        agent_id=agent.id,
        persona_id=result.persona_id,
    )
    db_session.add(suite)
    db_session.commit()
    evaluator = make_evaluator(
        agent_id=agent.id,
        persona_id=result.persona_id,
        scenario_id=scenario.id,
        suite_id=suite.id,
    )
    make_evaluator_result(
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        persona_id=result.persona_id,
        scenario_id=scenario.id,
        status="completed",
        metric_scores={
            str(metric.id): {
                "value": False,
                "type": "boolean",
                "metric_name": "Pass/Fail",
                "rationale": "Another failure.",
            }
        },
    )
    assert is_cluster_job_stale(db_session, job) is True


def test_metric_clusters_state_from_raw_parses_generation_scope():
    from app.services.call_import_metric_clusters import metric_clusters_state_from_raw

    raw = {
        "status": "completed",
        "groups": [],
        "discovered_problems": [],
        "generated_at_completed_rows": 5,
        "generation_scope": {
            "agent_id": str(uuid4()),
            "agent_name": "Agent X",
            "scenario_names": ["One"],
            "eligible_call_count": 4,
            "selected_call_count": 2,
        },
    }
    state = metric_clusters_state_from_raw(raw, completed_rows=5)
    assert state is not None
    assert state.generation_scope is not None
    assert state.generation_scope.agent_name == "Agent X"
    assert state.generation_scope.scenario_names == ["One"]
    assert state.generation_scope.selected_call_count == 2
