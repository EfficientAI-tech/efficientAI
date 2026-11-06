"""Agent + scenario scope filtering for metrics."""

from uuid import uuid4

import pytest

from app.models.database import Agent, Metric, Scenario
from app.services.metrics.evaluation_scope import (
    agent_ids_for_response,
    applicable_metrics,
    is_fully_golden,
    metric_applies_to_agent,
    metric_applies_to_scenario,
    replace_metric_agents,
    replace_metric_scenarios,
    scope_metric_id,
)
from app.services.metrics.scenario_scope import load_scenario_link_map


def test_agent_golden_and_scoped(db_session, org_id, default_workspace):
    agent_a = Agent(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Agent A",
    )
    agent_b = Agent(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Agent B",
    )
    golden = Metric(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Golden",
        metric_type="boolean",
    )
    scoped = Metric(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Agent only",
        metric_type="boolean",
    )
    db_session.add_all([agent_a, agent_b, golden, scoped])
    db_session.flush()
    replace_metric_agents(
        db_session,
        organization_id=org_id,
        metric=scoped,
        agent_ids=[agent_a.id],
    )
    db_session.commit()

    link_map = {scoped.id: frozenset({agent_a.id})}
    assert metric_applies_to_agent(scoped, agent_a.id, link_map=link_map)
    assert not metric_applies_to_agent(scoped, agent_b.id, link_map=link_map)
    assert metric_applies_to_agent(golden, agent_b.id, link_map={})

    filtered = applicable_metrics(
        [golden, scoped],
        agent_id=agent_b.id,
        scenario_id=None,
        db=db_session,
    )
    assert [m.id for m in filtered] == [golden.id]


def test_and_filter_agent_and_scenario(db_session, org_id, default_workspace):
    agent = Agent(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Prod",
    )
    scenario_x = Scenario(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=agent.id,
        name="X",
    )
    scenario_y = Scenario(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=agent.id,
        name="Y",
    )
    metric = Metric(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Both",
        metric_type="rating",
    )
    db_session.add_all([agent, scenario_x, scenario_y, metric])
    db_session.flush()
    replace_metric_agents(db_session, organization_id=org_id, metric=metric, agent_ids=[agent.id])
    replace_metric_scenarios(
        db_session, organization_id=org_id, metric=metric, scenario_ids=[scenario_x.id]
    )
    db_session.commit()

    ok = applicable_metrics(
        [metric], agent_id=agent.id, scenario_id=scenario_x.id, db=db_session
    )
    assert len(ok) == 1
    miss = applicable_metrics(
        [metric], agent_id=agent.id, scenario_id=scenario_y.id, db=db_session
    )
    assert miss == []


def test_child_inherits_parent_agent_links(db_session, org_id, default_workspace):
    agent = Agent(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="A",
    )
    parent = Metric(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Parent",
        metric_type="text",
        selection_mode="single_choice",
    )
    child = Metric(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Child",
        metric_type="boolean",
        parent_metric_id=None,
    )
    db_session.add_all([agent, parent])
    db_session.flush()
    child.parent_metric_id = parent.id
    db_session.add(child)
    db_session.flush()
    replace_metric_agents(db_session, organization_id=org_id, metric=parent, agent_ids=[agent.id])
    db_session.commit()
    db_session.refresh(child)

    assert agent_ids_for_response(child) == [agent.id]
    scope_id = scope_metric_id(child)
    agent_map = {parent.id: frozenset({agent.id})}
    assert metric_applies_to_agent(child, agent.id, link_map=agent_map)
    assert is_fully_golden(
        scope_id,
        agent_link_map=agent_map,
        scenario_link_map=load_scenario_link_map(db_session, [parent.id]),
    ) is False


def test_replace_metric_agents_rejects_child(db_session, org_id, default_workspace, make_metric):
    parent = make_metric(name="P", selection_mode="single_choice")
    child = make_metric(name="C", parent_metric_id=parent.id)
    with pytest.raises(ValueError, match="Child metrics"):
        replace_metric_agents(
            db_session,
            organization_id=org_id,
            metric=child,
            agent_ids=[uuid4()],
        )
