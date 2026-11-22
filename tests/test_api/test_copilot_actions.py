"""Copilot actions: propose -> confirm/reject/undo, plus each kind's wiring into existing routes."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.core.auth.capabilities import ALL_CAPABILITIES, SIM_VIEW
from app.models.database import (
    Agent,
    CallImport,
    CopilotAction,
    CopilotMessage,
    CopilotSession,
    Persona,
    Scenario,
    User,
)
from app.services.copilot import store
from app.services.copilot.actions import service
from app.services.copilot.registry import LLMChoice, ToolContext, execute

BASE = "/api/v1/copilot"


def _sessions(db_session):
    """Tools close their session; give them their own on the test transaction."""
    from sqlalchemy.orm import Session

    return lambda: Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")


@pytest.fixture
def chat(authenticated_client, db_session, org_id, default_workspace):
    """A session owned by the authenticated user plus a ToolContext for it."""
    session_id = UUID(authenticated_client.post(f"{BASE}/sessions", json={}).json()["id"])
    session = db_session.get(CopilotSession, session_id)
    ctx = ToolContext(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        user_id=session.user_id,
        capabilities=frozenset(ALL_CAPABILITIES),
        timezone="UTC",
        session_id=session_id,
        llm=LLMChoice(provider=None, model="", credential_id=None),
    )
    return SimpleNamespace(session=session, ctx=ctx, client=authenticated_client)


def _propose(db_session, ctx, tool, args) -> str:
    result = execute(ctx, tool, args, session_factory=_sessions(db_session))
    assert result.status == "ok", result.content
    data = json.loads(result.content)
    assert data["status"] == "awaiting_user_confirmation"
    assert result.ui["type"] == "proposal" and result.ui["action"]["status"] == "proposed"
    return data["action_id"]


def _events(db_session, session_id) -> list[str]:
    return [
        m.content for m in db_session.query(CopilotMessage)
        .filter(CopilotMessage.session_id == session_id, CopilotMessage.role == "event")
        .order_by(CopilotMessage.seq)
    ]


# --- lifecycle ----------------------------------------------------------------------


def test_persona_proposal_confirm_and_undo(chat, db_session, default_workspace):
    action_id = _propose(db_session, chat.ctx, "propose_create_persona", {
        "name": "Impatient Ivan", "description": "Angry, interrupts, wants a refund now.",
    })
    # Proposing changed nothing.
    assert db_session.query(Persona).filter(Persona.name == "Impatient Ivan").count() == 0

    confirmed = chat.client.post(f"{BASE}/actions/{action_id}/confirm", json={})
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "applied" and body["undoable"] is True
    created = body["result"]["created"][0]
    persona = db_session.get(Persona, UUID(created["id"]))
    assert persona.workspace_id == default_workspace.id and persona.name == "Impatient Ivan"
    assert "confirmed" in _events(db_session, chat.session.id)[-1]

    # A second confirm (double click, other tab) is refused.
    assert chat.client.post(f"{BASE}/actions/{action_id}/confirm", json={}).status_code == 409

    undone = chat.client.post(f"{BASE}/actions/{action_id}/undo")
    assert undone.status_code == 200 and undone.json()["status"] == "undone"
    db_session.expire_all()
    assert db_session.get(Persona, persona.id) is None
    assert chat.client.post(f"{BASE}/actions/{action_id}/undo").status_code == 409


def test_confirm_applies_user_edits(chat, db_session):
    action_id = _propose(db_session, chat.ctx, "propose_create_persona", {"name": "Draft name", "description": "d"})
    body = chat.client.post(
        f"{BASE}/actions/{action_id}/confirm", json={"payload": {"name": "Edited name", "description": "d"}}
    ).json()
    assert body["status"] == "applied" and body["payload"]["name"] == "Edited name"
    assert db_session.query(Persona).filter(Persona.name == "Edited name").count() == 1
    bad = _propose(db_session, chat.ctx, "propose_create_persona", {"name": "x", "description": "d"})
    assert chat.client.post(f"{BASE}/actions/{bad}/confirm", json={"payload": {"name": ""}}).status_code == 422


def test_reject_and_expiry(chat, db_session):
    rejected = _propose(db_session, chat.ctx, "propose_create_persona", {"name": "No", "description": "d"})
    assert chat.client.post(f"{BASE}/actions/{rejected}/reject").json()["status"] == "rejected"
    assert chat.client.post(f"{BASE}/actions/{rejected}/confirm", json={}).status_code == 409
    assert "rejected" in _events(db_session, chat.session.id)[-1]

    stale = _propose(db_session, chat.ctx, "propose_create_persona", {"name": "Old", "description": "d"})
    row = db_session.get(CopilotAction, UUID(stale))
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    assert chat.client.get(f"{BASE}/actions/{stale}").json()["status"] == "expired"
    assert chat.client.post(f"{BASE}/actions/{stale}/confirm", json={}).status_code == 409
    assert db_session.query(Persona).filter(Persona.name == "Old").count() == 0

    listed = chat.client.get(f"{BASE}/sessions/{chat.session.id}/actions").json()["items"]
    assert {a["id"] for a in listed} == {rejected, stale}


def test_actions_are_private_to_their_user(chat, db_session, org_id, default_workspace):
    other = User(id=uuid4(), email="other@example.com", name="O", is_active=True)
    db_session.add(other)
    db_session.flush()
    session = store.create_session(db_session, organization_id=org_id, workspace_id=default_workspace.id, user_id=other.id)
    ctx = ToolContext(**{**chat.ctx.__dict__, "user_id": other.id, "session_id": session.id})
    theirs = _propose(db_session, ctx, "propose_create_persona", {"name": "Theirs", "description": "d"})
    assert chat.client.post(f"{BASE}/actions/{theirs}/confirm", json={}).status_code == 404


def test_capability_checked_at_propose_and_confirm(chat, db_session):
    viewer = ToolContext(**{**chat.ctx.__dict__, "capabilities": frozenset({SIM_VIEW})})
    refused = execute(viewer, "propose_create_persona", {"name": "x", "description": "d"}, session_factory=_sessions(db_session))
    assert refused.status == "error"  # tool isn't offered without sim.manage

    action_id = _propose(db_session, chat.ctx, "propose_create_persona", {"name": "x", "description": "d"})
    row = db_session.get(CopilotAction, UUID(action_id))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.confirm(db_session, row, capabilities=frozenset({SIM_VIEW})))
    assert exc.value.status_code == 403
    db_session.refresh(row)
    assert row.status == "proposed"


def test_failed_apply_is_recorded(chat, db_session, monkeypatch):
    async def boom(**kwargs):
        raise HTTPException(status_code=409, detail="A persona with that name already exists.")

    monkeypatch.setattr("app.api.v1.routes.personas.create_persona", boom)
    action_id = _propose(db_session, chat.ctx, "propose_create_persona", {"name": "Dup", "description": "d"})
    body = chat.client.post(f"{BASE}/actions/{action_id}/confirm", json={}).json()
    assert body["status"] == "failed" and "already exists" in body["error"]
    assert "failed" in _events(db_session, chat.session.id)[-1]


def test_update_persona_undo_refuses_after_later_edit(chat, db_session, make_persona):
    persona = make_persona(name="Calm Carla")
    action_id = _propose(db_session, chat.ctx, "propose_update_persona", {
        "persona_id": str(persona.id), "description": "Now impatient.",
    })
    assert chat.client.post(f"{BASE}/actions/{action_id}/confirm", json={}).json()["status"] == "applied"
    db_session.refresh(persona)
    assert persona.description == "Now impatient."
    persona.description = "Edited by hand later"
    db_session.commit()
    refused = chat.client.post(f"{BASE}/actions/{action_id}/undo")
    assert refused.status_code == 409 and "edited again" in refused.json()["detail"]
    assert chat.client.get(f"{BASE}/actions/{action_id}").json()["status"] == "applied"


def test_update_without_changes_is_rejected(chat, db_session, make_persona):
    persona = make_persona()
    result = execute(chat.ctx, "propose_update_persona", {"persona_id": str(persona.id)}, session_factory=_sessions(db_session))
    assert result.status == "error" and "nothing to change" in result.content


# --- test setup bundle ------------------------------------------------------------------


def test_save_test_setup_from_draft_and_undo(chat, db_session, make_agent):
    agent = make_agent(name="Billing bot", agent_id="555111")
    no_draft = execute(chat.ctx, "propose_save_test_setup", {}, session_factory=_sessions(db_session))
    assert no_draft.status == "error" and "generate_test_setup" in no_draft.content

    chat.session.draft = {"test_setup": {
        "agent_id": str(agent.id),
        "sections": [{"key": "complementary_goal", "title": "Goal", "content": "Get a refund."}],
        "first_message": {"caller_mode": "speak_first", "caller_message": "Hi, I was double charged."},
        "scenarios": [
            {"name": "Double charge", "description": "Caller was billed twice.", "goal": "Refund"},
            {"name": "Cancel plan", "description": "Caller wants to cancel."},
        ],
    }}
    db_session.commit()
    action_id = _propose(db_session, chat.ctx, "propose_save_test_setup", {
        "scenario_names": ["Double charge"],
        "personas": [{"name": "Angry Ann", "description": "Furious about the charge."}],
    })
    body = chat.client.post(f"{BASE}/actions/{action_id}/confirm", json={}).json()
    assert body["status"] == "applied", body
    db_session.expire_all()
    agent = db_session.get(Agent, agent.id)
    assert agent.test_agent_template["sections"][0]["content"] == "Get a refund."
    scenarios = db_session.query(Scenario).filter(Scenario.agent_id == agent.id).all()
    assert [s.name for s in scenarios] == ["Double charge"] and "Goal: Refund" in scenarios[0].description
    persona = db_session.query(Persona).filter(Persona.name == "Angry Ann").one()
    assert persona.simulation_medium in ("voice", "text")

    assert chat.client.post(f"{BASE}/actions/{action_id}/undo").json()["status"] == "undone"
    db_session.expire_all()
    assert db_session.query(Scenario).filter(Scenario.agent_id == agent.id).count() == 0
    assert db_session.query(Persona).filter(Persona.name == "Angry Ann").count() == 0
    assert db_session.get(Agent, agent.id).test_agent_template is None


# --- costly kinds call routes with explicit parameters ------------------------------------


def test_simulation_run_estimate_and_wiring(chat, db_session, make_agent, monkeypatch):
    agent = make_agent(agent_id="777001")
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(run_id="314159", name=None, expected_trials=6, status="queued")

    monkeypatch.setattr("app.api.v1.routes.simulation_runs.create_simulation_run", fake_create)
    action_id = _propose(db_session, chat.ctx, "propose_start_simulation_run", {
        "agent_id": str(agent.id), "scenario_ids": [str(uuid4()), str(uuid4())],
        "persona_ids": [str(uuid4())], "n_attempts": 3,
    })
    card = chat.client.get(f"{BASE}/actions/{action_id}").json()
    assert card["costly"] is True and card["cost_estimate"]["simulated_calls"] == 6
    body = chat.client.post(f"{BASE}/actions/{action_id}/confirm", json={}).json()
    assert body["status"] == "applied" and body["result"]["created"][0]["link"] == "/simulations/314159"
    assert captured["principal"].user_id == chat.session.user_id
    assert captured["workspace_id"] == chat.ctx.workspace_id
    assert captured["payload"].n_attempts == 3


def test_import_evaluation_uses_production_transcripts_and_default_llm(
    chat, db_session, org_id, default_workspace, ai_provider_row, monkeypatch
):
    call_import = CallImport(
        id=uuid4(), organization_id=org_id, workspace_id=default_workspace.id,
        original_filename="calls.csv", total_rows=40, status="completed",
    )
    db_session.add(call_import)
    db_session.commit()
    captured = {}

    def fake_create(db, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4(), name="Eval", total_rows=40)

    monkeypatch.setattr(
        "app.services.call_imports.evaluation_create.create_call_import_evaluations", fake_create
    )
    monkeypatch.setattr("app.core.license.is_feature_enabled", lambda feature, org: True)
    metric_id = str(uuid4())
    action_id = _propose(db_session, chat.ctx, "propose_start_import_evaluation", {
        "call_import_id": str(call_import.id), "metric_ids": [metric_id],
    })
    estimate = chat.client.get(f"{BASE}/actions/{action_id}").json()["cost_estimate"]
    assert estimate["calls_to_evaluate"] == 40 and estimate["llm_judgements"] == 40
    body = chat.client.post(f"{BASE}/actions/{action_id}/confirm", json={}).json()
    assert body["status"] == "applied", body
    payload = captured["payload"]
    assert payload.transcript_sources == ["production"] and payload.auto_transcribe is False
    assert payload.llm_model == "gpt-4o-mini" and payload.llm_credential_id == ai_provider_row.id


def test_import_actions_respect_enterprise_gate(chat, db_session, monkeypatch):
    monkeypatch.setattr("app.core.license.is_feature_enabled", lambda feature, org: False)
    action_id = _propose(db_session, chat.ctx, "propose_cancel_import_evaluation", {"evaluation_id": str(uuid4())})
    body = chat.client.post(f"{BASE}/actions/{action_id}/confirm", json={}).json()
    assert body["status"] == "failed" and "Enterprise" in body["error"]


def test_retry_passes_body_explicitly(chat, db_session, org_id, default_workspace, monkeypatch):
    from app.models.database import CallImportEvaluation

    call_import = CallImport(id=uuid4(), organization_id=org_id, workspace_id=default_workspace.id, total_rows=2, status="completed")
    db_session.add(call_import)
    db_session.flush()
    evaluation = CallImportEvaluation(
        id=uuid4(), call_import_id=call_import.id, organization_id=org_id, workspace_id=default_workspace.id,
        selected_metric_ids=[], status="completed", total_rows=2, completed_rows=1, failed_rows=1,
    )
    db_session.add(evaluation)
    db_session.commit()
    seen = {}

    async def fake_retry(**kwargs):
        seen.update(kwargs)
        return {"requeued": 1}

    monkeypatch.setattr(
        "app.api.v1.routes.call_import_evaluations.evaluation_retry.retry_call_import_evaluation", fake_retry
    )
    monkeypatch.setattr("app.core.license.is_feature_enabled", lambda feature, org: True)
    action_id = _propose(db_session, chat.ctx, "propose_retry_import_evaluation", {"evaluation_id": str(evaluation.id)})
    assert chat.client.get(f"{BASE}/actions/{action_id}").json()["cost_estimate"] == {"failed_calls_to_retry": 1}
    assert chat.client.post(f"{BASE}/actions/{action_id}/confirm", json={}).json()["status"] == "applied"
    assert "payload" in seen and seen["payload"] is None  # not the truthy Body() FieldInfo default


@pytest.fixture
def ai_provider_row(db_session, org_id, seed_org):
    from app.models.database import AIProvider

    row = AIProvider(
        id=uuid4(), organization_id=org_id, provider="openai", api_key="enc", name="Primary",
        is_active=True, is_default=True, enabled_models=["gpt-4o-mini"],
    )
    db_session.add(row)
    db_session.commit()
    return row


# --- events reach the model ------------------------------------------------------------------


def test_confirmations_are_folded_into_next_user_message(chat, db_session):
    rows = store.begin_turn(db_session, chat.session, content="make a persona", client_message_id=None, page_context=None)
    store.finish_turn(
        db_session, rows.assistant_message.id, content="Here's a card to confirm.", steps=[], status="complete",
        error=None, model="m", prompt_tokens=0, completion_tokens=0, latency_ms=1, session_id=chat.session.id,
    )
    store.add_event(db_session, chat.session.id, 'The user confirmed "Create persona". Created persona X.')
    db_session.refresh(chat.session)
    nxt = store.begin_turn(db_session, chat.session, content="now a scenario", client_message_id=None, page_context=None)
    history = store.history_for_llm(db_session, chat.session.id, up_to_seq=nxt.user_message.seq, limit=20)
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert history[-1]["content"].startswith("[Update since your last reply: The user confirmed")
    assert history[-1]["content"].endswith("now a scenario")
    roles = [m["role"] for m in chat.client.get(f"{BASE}/sessions/{chat.session.id}/messages").json()["items"]]
    assert roles == ["user", "assistant", "event", "user", "assistant"]
