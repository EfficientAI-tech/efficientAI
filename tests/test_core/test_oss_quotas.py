"""Unit tests for OSS quantity limits."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core import oss_quotas as quotas_module
from app.models.database import Agent, Metric, Workspace
from app.models.enums import MetricTrigger, MetricType


def _add_agent(db_session, org_id, workspace_id, *, name: str, agent_id: str | None = None):
    agent = Agent(
        id=uuid4(),
        agent_id=agent_id or str(uuid4().int % 900000 + 100000),
        organization_id=org_id,
        workspace_id=workspace_id,
        name=name,
        language="en",
        call_type="outbound",
        call_medium="web_call",
    )
    db_session.add(agent)
    db_session.commit()
    return agent


def _add_metric(
    db_session,
    org_id,
    workspace_id,
    *,
    name: str,
    is_default: bool = False,
    metric_origin: str = "custom",
):
    metric = Metric(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        name=name,
        metric_type=MetricType.RATING.value,
        trigger=MetricTrigger.ALWAYS.value,
        enabled=True,
        is_default=is_default,
        metric_origin=metric_origin,
        supported_surfaces=["agent"],
        enabled_surfaces=["agent"],
    )
    db_session.add(metric)
    db_session.commit()
    return metric


def test_enforce_oss_quota_skipped_with_entitlement(db_session, org_id, monkeypatch):
    monkeypatch.setattr(
        quotas_module,
        "has_enterprise_entitlement",
        lambda _org: True,
    )

    quotas_module.enforce_oss_quota(db_session, org_id, "agents", additional=100)


def test_enforce_agent_quota_blocks_fourth_agent(
    db_session, org_id, seed_org, default_workspace, monkeypatch
):
    monkeypatch.setattr(
        quotas_module,
        "has_enterprise_entitlement",
        lambda _org: False,
    )

    for idx in range(3):
        _add_agent(
            db_session,
            org_id,
            default_workspace.id,
            name=f"Agent {idx}",
            agent_id=f"{100000 + idx}",
        )

    with pytest.raises(HTTPException) as exc:
        quotas_module.enforce_oss_quota(db_session, org_id, "agents")

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "oss_quota_exceeded"
    assert exc.value.detail["resource"] == "agents"
    assert exc.value.detail["limit"] == 3


def test_user_metrics_exclude_defaults(
    db_session, org_id, seed_org, default_workspace, monkeypatch
):
    monkeypatch.setattr(
        quotas_module,
        "has_enterprise_entitlement",
        lambda _org: False,
    )

    _add_metric(
        db_session,
        org_id,
        default_workspace.id,
        name="Default Metric",
        is_default=True,
        metric_origin="default",
    )
    for idx in range(5):
        _add_metric(
            db_session,
            org_id,
            default_workspace.id,
            name=f"Custom {idx}",
            is_default=False,
            metric_origin="custom",
        )

    with pytest.raises(HTTPException) as exc:
        quotas_module.enforce_oss_quota(db_session, org_id, "metrics")

    assert exc.value.detail["resource"] == "metrics"
    assert exc.value.detail["limit"] == 5
    assert exc.value.detail["current"] == 5


def test_workspace_quota_blocks_second_workspace(
    db_session, org_id, seed_org, default_workspace, monkeypatch
):
    monkeypatch.setattr(
        quotas_module,
        "has_enterprise_entitlement",
        lambda _org: False,
    )

    # OSS orgs start with one default workspace; creating another should hit the cap.
    assert (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id)
        .count()
        == 1
    )

    with pytest.raises(HTTPException) as exc:
        quotas_module.enforce_oss_quota(db_session, org_id, "workspaces")

    assert exc.value.detail["resource"] == "workspaces"
    assert exc.value.detail["limit"] == 1
    assert exc.value.detail["current"] == 1
