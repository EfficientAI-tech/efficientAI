"""Shared rows for red team tests."""

from types import SimpleNamespace

import pytest

from app.models.database import Agent, RedTeamRun
from app.models.enums import RedTeamRunStatus
from app.services.red_team.catalog import CATALOG_VERSION
from app.services.red_team.presets import resolve_config


@pytest.fixture
def chat_agent(db_session, seed_org, default_workspace):
    agent = Agent(
        organization_id=seed_org.id,
        workspace_id=default_workspace.id,
        agent_id="424242",
        name="Bank Helper",
        call_type="inbound",
        call_medium="chat",
        description="Helps bank customers with balances and card changes.",
        provider_prompt="You are a bank assistant. Verify identity with date of birth before sharing account data.",
        main_llm_provider="openai",
        main_llm_model="gpt-4.1-mini",
        test_llm_provider="openai",
        test_llm_model="gpt-4.1-mini",
    )
    db_session.add(agent)
    db_session.commit()
    return agent


@pytest.fixture
def make_run(db_session, chat_agent):
    def _make(intensity="quick", **kwargs):
        config = resolve_config(intensity, modality="chat", attack_quotas=kwargs.pop("attack_quotas", None))
        config.update(kwargs.pop("config", {}))
        run = RedTeamRun(
            run_id=kwargs.pop("run_id", "900001"),
            organization_id=chat_agent.organization_id,
            workspace_id=chat_agent.workspace_id,
            agent_id=chat_agent.id,
            intensity=intensity,
            modality="chat",
            config=config,
            catalog_version=CATALOG_VERSION,
            status=RedTeamRunStatus.QUEUED.value,
            max_attacks=config["max_attacks"],
            **kwargs,
        )
        db_session.add(run)
        db_session.commit()
        return run

    return _make


@pytest.fixture
def rt(chat_agent, make_run):
    return SimpleNamespace(agent=chat_agent, make_run=make_run)
