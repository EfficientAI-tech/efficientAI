"""Unit tests for scenario-to-metric generation helpers."""

from __future__ import annotations

from uuid import uuid4

from app.models.enums import ModelProvider
from app.services.testing import scenario_metric_generation as smg


def test_evaluation_surface_for_call_medium():
    assert smg.evaluation_surface_for_call_medium("chat") == "chat_agent"
    assert smg.evaluation_surface_for_call_medium("voice") == "agent"
    assert smg.evaluation_surface_for_call_medium(None) == "agent"


def test_normalize_generated_metric_fields_defaults_enum_for_rating():
    normalized = smg.normalize_generated_metric_fields(
        {"name": "Handled Refund", "description": "Did the agent process the refund?"},
        surface="agent",
    )
    assert normalized["metric_type"] == "rating"
    assert normalized["custom_data_type"] == "enum"
    assert normalized["supported_surfaces"] == ["agent"]
    assert normalized["enabled_surfaces"] == ["agent"]


def test_build_messages_includes_production_prompt_and_scenarios():
    messages = smg._build_messages(
        agent_name="Support Bot",
        production_prompt="You help customers with billing.",
        surface="chat_agent",
        scenarios=[
            smg.ScenarioMetricInput(name="Late fee dispute", description="Customer disputes a fee."),
        ],
    )
    user = messages[1]["content"]
    assert "Support Bot" in user
    assert "You help customers with billing." in user
    assert "Late fee dispute" in user
    assert "chat_agent" in user


def test_build_tags_includes_agent_and_auto_generated():
    tags = smg._build_tags("My Agent", ["qa", "auto-generated"])
    assert tags[0] == "My Agent"
    assert tags[1] == "auto-generated"
    assert "qa" in tags
    assert tags.count("auto-generated") == 1


def test_generate_metrics_from_scenarios_parses_llm_array(monkeypatch, db_session, org_id):
    workspace_id = uuid4()

    captured = {}

    def fake_llm(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return {
            "text": """[
              {
                "name": "Refund Handled",
                "description": "Agent followed refund policy.",
                "metric_type": "boolean",
                "custom_data_type": "boolean",
                "custom_config": {},
                "supported_surfaces": ["agent"],
                "enabled_surfaces": ["agent"]
              }
            ]"""
        }

    monkeypatch.setattr(smg.llm_service, "generate_response", fake_llm)

    result = smg.generate_metrics_from_scenarios(
        agent_name="Billing Agent",
        production_prompt="Handle refunds politely.",
        call_medium="voice",
        scenarios=[
            smg.ScenarioMetricInput(
                name="Refund request",
                description="Caller wants money back.",
                goal="Issue refund",
            )
        ],
        organization_id=org_id,
        workspace_id=workspace_id,
        db=db_session,
        llm_provider=ModelProvider.OPENAI,
        llm_model="gpt-test",
    )

    assert len(result.metrics) == 1
    metric = result.metrics[0]
    assert metric.name == "Refund Handled"
    assert metric.metric_type == "boolean"
    assert metric.scenario_name == "Refund request"
    assert metric.tags[:2] == ["Billing Agent", "auto-generated"]
    assert captured["messages"][0]["role"] == "system"
