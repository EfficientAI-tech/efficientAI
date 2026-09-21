"""API tests for OSS vs enterprise feature gates (unlicensed client)."""

from __future__ import annotations

import pytest

import app.dependencies as app_dependencies
from app.core import license as license_module


@pytest.fixture
def unlicensed_client(authenticated_client):
    """Authenticated client with real license checks and no enterprise JWT."""
    license_module.reset_license_cache()
    license_module._license_cache = {}
    app_dependencies.is_feature_enabled = license_module.is_feature_enabled
    yield authenticated_client
    app_dependencies.is_feature_enabled = lambda *_args, **_kwargs: True
    license_module.reset_license_cache()


def test_alerts_forbidden_without_license(unlicensed_client):
    payload = {
        "name": "OSS Alert",
        "metric_type": "number_of_calls",
        "aggregation": "sum",
        "operator": ">",
        "threshold_value": 10,
        "time_window_minutes": 60,
        "notify_frequency": "immediate",
    }
    response = unlicensed_client.post("/api/v1/alerts", json=payload)
    assert response.status_code == 403
    assert response.json()["detail"]["feature"] == "alerts"


def test_metric_studio_forbidden_without_license(unlicensed_client):
    response = unlicensed_client.get("/api/v1/metric-studio/runs")
    assert response.status_code == 403
    assert response.json()["detail"]["feature"] == "metric_studio"


def test_prompt_optimization_allowed_without_license(unlicensed_client, make_agent):
    agent = make_agent(description="GEPA OSS")
    response = unlicensed_client.post(
        "/api/v1/prompt-optimization/runs",
        json={"agent_id": str(agent.id), "config": {"max_iterations": 1}},
    )
    assert response.status_code == 201


def test_llm_gateway_enable_forbidden_without_license(unlicensed_client):
    response = unlicensed_client.put(
        "/api/v1/organizations/llm-gateway",
        json={"mode": "enabled", "gateway_type": "inherit", "gateway_interface": "inherit"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["feature"] == "llm_gateway"


def test_license_info_includes_oss_quotas(unlicensed_client):
    response = unlicensed_client.get("/api/v1/settings/license-info")
    assert response.status_code == 200
    body = response.json()
    assert body["quotas"]["max_user_metrics"] == 5
    assert body["quotas"]["max_agents"] == 3
    assert body["quotas"]["max_org_members"] == 1
    assert "quota_usage" in body


def test_workspace_iam_forbidden_without_license(unlicensed_client, default_workspace):
    response = unlicensed_client.get(
        f"/api/v1/workspaces/{default_workspace.id}/members"
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "enterprise_license_required"
