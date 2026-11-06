"""Shared rows for Harbor simulation run tests."""

from types import SimpleNamespace

import pytest

from app.models.database import Agent, Metric, Persona, Scenario, SimulationRun
from app.models.enums import SimulationRunStatus


@pytest.fixture
def harbor_work_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "HARBOR_WORK_DIR", str(tmp_path / "harbor"))
    return tmp_path / "harbor"


@pytest.fixture
def sim_rows(db_session, seed_org, default_workspace):
    org_id, workspace_id = seed_org.id, default_workspace.id
    agent = Agent(
        organization_id=org_id,
        workspace_id=workspace_id,
        agent_id="314159",
        name="Support Bot",
        call_type="inbound",
        call_medium="chat",
        description="You help customers with refunds.",
        main_llm_provider="openai",
        main_llm_model="gpt-4.1-mini",
        test_llm_provider="openai",
        test_llm_model="gpt-4.1-mini",
    )
    db_session.add(agent)
    db_session.flush()
    persona = Persona(
        organization_id=org_id, workspace_id=workspace_id, name="Angry Alex", max_turns=4
    )
    scenario = Scenario(
        organization_id=org_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        name="Refund for late order",
        description="Customer wants a refund for an order that arrived late.",
    )
    metric = Metric(
        organization_id=org_id,
        workspace_id=workspace_id,
        name="Empathy",
        description="Did the agent show empathy?",
        metric_type="rating",
    )
    db_session.add_all([persona, scenario, metric])
    db_session.flush()
    run = SimulationRun(
        run_id="271828",
        organization_id=org_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        scenario_ids=[str(scenario.id)],
        persona_ids=[str(persona.id)],
        n_attempts=2,
        n_concurrent=2,
        pass_threshold=0.7,
        status=SimulationRunStatus.QUEUED.value,
    )
    db_session.add(run)
    db_session.commit()
    return SimpleNamespace(agent=agent, persona=persona, scenario=scenario, metric=metric, run=run)
