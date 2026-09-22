"""API tests for OSS vs enterprise feature gates (unlicensed client)."""

from __future__ import annotations

import pytest

from app.core import license as license_module


@pytest.fixture
def unlicensed_client(authenticated_client, monkeypatch):
    """Authenticated client with real license checks and no enterprise JWT."""
    import app.dependencies as app_dependencies
    from app.config import settings

    monkeypatch.setattr(settings, "EFFICIENTAI_LICENSE", None, raising=False)
    monkeypatch.delenv("EFFICIENTAI_LICENSE", raising=False)
    license_module.reset_license_cache()
    # conftest._build_session_api_app() stubs app.dependencies.is_feature_enabled;
    # require_enterprise_feature() resolves that name at call time.
    monkeypatch.setattr(
        app_dependencies,
        "is_feature_enabled",
        license_module.is_feature_enabled,
    )

    yield authenticated_client

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
    assert response.json()["detail"]["error"] == "enterprise_license_required"


def test_aiprovider_gateway_routing_forbidden_without_license(unlicensed_client):
    response = unlicensed_client.post(
        "/api/v1/aiproviders",
        json={
            "provider": "openai",
            "name": "OSS should not gateway",
            "routing_mode": "gateway",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "enterprise_license_required"


def test_aiprovider_inherit_routing_forbidden_without_license(unlicensed_client):
    response = unlicensed_client.post(
        "/api/v1/aiproviders",
        json={
            "provider": "openai",
            "name": "OSS inherit blocked",
            "routing_mode": "inherit",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "enterprise_license_required"


def test_aiprovider_direct_routing_allowed_without_license(unlicensed_client):
    response = unlicensed_client.post(
        "/api/v1/aiproviders",
        json={
            "provider": "openai",
            "name": "OSS direct ok",
            "api_key": "sk-test-direct-only",
            "routing_mode": "direct",
        },
    )
    assert response.status_code == 201
    assert response.json()["routing_mode"] == "direct"


def test_license_info_includes_oss_quotas(unlicensed_client):
    response = unlicensed_client.get("/api/v1/settings/license-info")
    assert response.status_code == 200
    body = response.json()
    assert body["quotas"]["max_user_metrics"] == 5
    assert body["quotas"]["max_agents"] == 3
    assert body["quotas"]["max_org_members"] == 1
    assert "quota_usage" in body


def test_update_gateway_aiprovider_name_allowed_without_license(
    unlicensed_client, db_session, org_id
):
    from app.core.encryption import encrypt_api_key
    from app.models.database import AIProvider
    from app.services.ai.llm_gateway import GATEWAY_MANAGED_KEY_SENTINEL

    row = AIProvider(
        organization_id=org_id,
        provider="openai",
        api_key=encrypt_api_key(GATEWAY_MANAGED_KEY_SENTINEL),
        name="Before",
        routing_mode="gateway",
        gateway_model="prod-gpt4",
        is_active=True,
    )
    db_session.add(row)
    db_session.commit()

    response = unlicensed_client.put(
        f"/api/v1/aiproviders/{row.id}",
        json={"name": "After"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "After"
    assert body["routing_mode"] == "gateway"
    assert body["gateway_model"] == "prod-gpt4"


def test_update_gateway_aiprovider_api_key_allowed_without_license(
    unlicensed_client, db_session, org_id
):
    from app.core.encryption import encrypt_api_key
    from app.models.database import AIProvider
    from app.services.ai.llm_gateway import GATEWAY_MANAGED_KEY_SENTINEL

    row = AIProvider(
        organization_id=org_id,
        provider="openai",
        api_key=encrypt_api_key(GATEWAY_MANAGED_KEY_SENTINEL),
        name="Gateway row",
        routing_mode="inherit",
        is_active=True,
    )
    db_session.add(row)
    db_session.commit()

    response = unlicensed_client.put(
        f"/api/v1/aiproviders/{row.id}",
        json={"api_key": "sk-test-direct-key"},
    )
    assert response.status_code == 200
    assert response.json()["routing_mode"] == "inherit"


def test_update_aiprovider_gateway_field_blocked_without_license(
    unlicensed_client, db_session, org_id
):
    from app.core.encryption import encrypt_api_key
    from app.models.database import AIProvider
    from app.services.ai.llm_gateway import GATEWAY_MANAGED_KEY_SENTINEL

    row = AIProvider(
        organization_id=org_id,
        provider="openai",
        api_key=encrypt_api_key(GATEWAY_MANAGED_KEY_SENTINEL),
        name="Gateway row",
        routing_mode="gateway",
        gateway_model="prod-gpt4",
        is_active=True,
    )
    db_session.add(row)
    db_session.commit()

    response = unlicensed_client.put(
        f"/api/v1/aiproviders/{row.id}",
        json={"gateway_model": "new-production-model"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "enterprise_license_required"


def test_update_aiprovider_routing_mode_gateway_blocked_without_license(
    unlicensed_client, db_session, org_id
):
    from app.core.encryption import encrypt_api_key
    from app.models.database import AIProvider

    row = AIProvider(
        organization_id=org_id,
        provider="openai",
        api_key=encrypt_api_key("sk-existing-direct"),
        name="Direct row",
        routing_mode="direct",
        is_active=True,
    )
    db_session.add(row)
    db_session.commit()

    response = unlicensed_client.put(
        f"/api/v1/aiproviders/{row.id}",
        json={"routing_mode": "gateway"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "enterprise_license_required"


def test_workspace_iam_forbidden_without_license(unlicensed_client, default_workspace):
    response = unlicensed_client.get(
        f"/api/v1/workspaces/{default_workspace.id}/members"
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "enterprise_license_required"
