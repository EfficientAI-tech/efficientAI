"""Scenario scope helpers for golden vs linked metrics."""

from uuid import uuid4

import pytest

from app.models.database import Metric, MetricScenarioAssignment, Scenario
from app.services.metrics.evaluation_scope import applicable_metrics
from app.services.metrics.scenario_scope import (
    is_golden_scope,
    load_scenario_link_map,
    metric_applies_to_scenario,
    replace_metric_scenarios,
)


def _metric(mid=None, parent_id=None):
    m = Metric(id=mid or uuid4(), name="m", organization_id=uuid4())
    m.parent_metric_id = parent_id
    m.scoped_scenarios = []
    return m


def test_applicable_metrics_golden_always_applies():
    golden = _metric()
    sid = uuid4()
    out = applicable_metrics(
        [golden],
        scenario_id=sid,
        agent_link_map={},
        scenario_link_map={},
    )
    assert out == [golden]


def test_applicable_metrics_linked_only_on_matching_scenario():
    mid = uuid4()
    linked_sid = uuid4()
    other_sid = uuid4()
    metric = _metric(mid)
    link_map = {mid: frozenset({linked_sid})}
    assert (
        applicable_metrics(
            [metric],
            scenario_id=linked_sid,
            agent_link_map={},
            scenario_link_map=link_map,
        )
        == [metric]
    )
    assert (
        applicable_metrics(
            [metric],
            scenario_id=other_sid,
            agent_link_map={},
            scenario_link_map=link_map,
        )
        == []
    )


def test_applicable_metrics_none_scenario_keeps_all():
    mid = uuid4()
    metric = _metric(mid)
    link_map = {mid: frozenset({uuid4()})}
    assert applicable_metrics([metric], scenario_id=None) == [metric]


def test_child_follows_parent_links(db_session, seed_org, default_workspace):
    org, ws = seed_org, default_workspace
    scenario = Scenario(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=ws.id,
        name="Refund",
    )
    parent = Metric(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=ws.id,
        name="Parent",
        metric_type="rating",
        enabled=True,
    )
    child = Metric(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=ws.id,
        name="Child",
        metric_type="boolean",
        parent_metric_id=parent.id,
        enabled=True,
    )
    db_session.add_all([scenario, parent, child])
    db_session.flush()
    replace_metric_scenarios(
        db_session,
        organization_id=org.id,
        metric=parent,
        scenario_ids=[scenario.id],
    )
    db_session.commit()
    link_map = load_scenario_link_map(db_session, [parent.id])
    assert not is_golden_scope(link_map, parent.id)
    assert metric_applies_to_scenario(child, scenario.id, link_map=link_map)
    assert not metric_applies_to_scenario(child, uuid4(), link_map=link_map)


def test_replace_metric_scenarios_rejects_child(db_session, seed_org, default_workspace):
    org, ws = seed_org, default_workspace
    parent = Metric(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=ws.id,
        name="P",
        metric_type="rating",
        enabled=True,
    )
    child = Metric(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=ws.id,
        name="C",
        metric_type="boolean",
        parent_metric_id=parent.id,
        enabled=True,
    )
    db_session.add_all([parent, child])
    db_session.flush()
    with pytest.raises(ValueError, match="Child metrics"):
        replace_metric_scenarios(
            db_session,
            organization_id=org.id,
            metric=child,
            scenario_ids=[uuid4()],
        )
