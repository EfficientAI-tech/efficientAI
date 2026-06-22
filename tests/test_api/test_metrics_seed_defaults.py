"""Tests for default metric seeding behavior."""

from uuid import uuid4

from app.models.database import Metric, Workspace
from app.models.enums import MetricCategory


def test_seed_defaults_excludes_user_insights_and_problem_resolution(
    authenticated_client, db_session, org_id, default_workspace
):
    response = authenticated_client.post("/api/v1/metrics/seed-defaults")
    assert response.status_code == 201

    metrics = authenticated_client.get("/api/v1/metrics").json()
    names = {m["name"] for m in metrics}

    assert "Follow Instructions" in names
    assert "Professionalism" in names
    assert "Problem Resolution" not in names
    assert "Caller Context Distribution" not in names

    user_insight_rows = (
        db_session.query(Metric)
        .filter(
            Metric.organization_id == org_id,
            Metric.workspace_id == default_workspace.id,
            Metric.metric_category == MetricCategory.USER_INSIGHT.value,
            Metric.is_default.is_(True),
        )
        .all()
    )
    assert user_insight_rows == []


def test_seed_defaults_disables_legacy_user_insight_metrics(
    authenticated_client, db_session, org_id, default_workspace
):
    legacy_parent = Metric(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Caller Context Distribution",
        description="Legacy default user insight",
        metric_type="text",
        metric_category=MetricCategory.USER_INSIGHT.value,
        trigger="always",
        enabled=True,
        is_default=True,
        metric_origin="default",
        supported_surfaces=["call_import"],
        enabled_surfaces=["call_import"],
    )
    db_session.add(legacy_parent)
    db_session.commit()

    response = authenticated_client.post("/api/v1/metrics/seed-defaults")
    assert response.status_code == 201

    db_session.refresh(legacy_parent)
    assert legacy_parent.enabled is False

    metrics = authenticated_client.get("/api/v1/metrics").json()
    names = {m["name"] for m in metrics}
    assert "Caller Context Distribution" not in names
