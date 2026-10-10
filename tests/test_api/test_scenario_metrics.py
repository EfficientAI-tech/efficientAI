"""API tests for scenario-to-metric generation."""

from __future__ import annotations

from unittest.mock import patch
import pytest

from app.core import license as license_module
from app.services.testing import scenario_metric_generation as smg


@pytest.fixture
def unlicensed_client(authenticated_client, monkeypatch):
    import app.dependencies as app_dependencies
    from app.config import settings

    monkeypatch.setattr(settings, "EFFICIENTAI_LICENSE", None, raising=False)
    monkeypatch.delenv("EFFICIENTAI_LICENSE", raising=False)
    monkeypatch.setattr(license_module, "get_license_info", lambda: {})
    license_module.reset_license_cache()
    monkeypatch.setattr(
        app_dependencies,
        "is_feature_enabled",
        license_module.is_feature_enabled,
    )
    yield authenticated_client
    license_module.reset_license_cache()


def test_generate_from_scenarios_forbidden_without_license(unlicensed_client):
    payload = {
        "agent_name": "Agent",
        "production_prompt": "Help users.",
        "scenarios": [{"name": "S1", "description": "Test scenario"}],
    }
    response = unlicensed_client.post("/api/v1/metrics/generate-from-scenarios", json=payload)
    assert response.status_code == 403
    assert response.json()["detail"]["feature"] == "scenario_metrics"


def test_generate_from_scenarios_returns_tagged_drafts(authenticated_client, make_agent):
    agent = make_agent(name="Tagged Agent", description="Production prompt body.")
    payload = {
        "agent_name": agent.name,
        "production_prompt": agent.description,
        "call_medium": "voice",
        "scenarios": [
            {
                "name": "Escalation",
                "description": "Customer asks for a supervisor.",
                "goal": "De-escalate",
            }
        ],
    }

    fake_metric = smg.ScenarioMetricDraft(
        name="Escalation Handled",
        description="Agent de-escalated appropriately.",
        metric_type="boolean",
        custom_data_type="boolean",
        custom_config={},
        supported_surfaces=["agent"],
        enabled_surfaces=["agent"],
        tags=["Tagged Agent", "auto-generated"],
        scenario_name="Escalation",
    )

    with patch(
        "app.api.v1.routes.scenario_metrics.generate_metrics_from_scenarios",
        return_value=smg.ScenarioMetricGenerationResult(
            metrics=[fake_metric],
            provider="openai",
            model="gpt-test",
        ),
    ):
        response = authenticated_client.post(
            "/api/v1/metrics/generate-from-scenarios",
            json=payload,
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["metrics"]) == 1
    assert body["metrics"][0]["tags"] == ["Tagged Agent", "auto-generated"]
    assert body["metrics"][0]["scenario_name"] == "Escalation"
