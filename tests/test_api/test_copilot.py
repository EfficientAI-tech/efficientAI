"""Copilot API: readiness, sessions, streamed turns with tools, and the guards around them."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth.capabilities import ALL_CAPABILITIES
from app.models.database import (
    AIProvider,
    CallImport,
    CallImportEvaluation,
    CopilotMessage,
    CopilotSession,
    User,
    Workspace,
)
from app.services.copilot import redis_state, store
from app.services.copilot.registry import LLMChoice, ToolContext, execute
from app.services.copilot.turn import TurnInput, run_turn

BASE = "/api/v1/copilot"


# --- fixtures -----------------------------------------------------------------


@pytest.fixture
def ai_provider(db_session, org_id, seed_org):
    row = AIProvider(
        id=uuid4(),
        organization_id=org_id,
        provider="openai",
        api_key="enc",
        name="Primary",
        is_active=True,
        is_default=True,
        enabled_models=["gpt-4o-mini"],
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def turn_db(monkeypatch, db_session):
    """Turn threads open their own sessions; point them at the test transaction."""

    def factory() -> Session:
        return Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")

    monkeypatch.setattr("app.services.copilot.turn.SessionLocal", factory)
    monkeypatch.setattr("app.services.copilot.registry.SessionLocal", factory)
    return factory


@pytest.fixture
def redis_available():
    try:
        redis_state._client().ping()
    except Exception:
        pytest.skip("test Redis not available")


class FakeLLM:
    """Scripted ``generate_response_with_tools``: each call pops the next reply."""

    def __init__(self, replies: list[dict[str, Any]]):
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, messages, tools, on_text_delta=None, db=None, release_db_before_call=False, **kwargs):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        text = reply.get("text", "")
        if on_text_delta and text:
            for i in range(0, len(text), 5):
                on_text_delta(text[i : i + 5])
        if release_db_before_call and db is not None:
            db.close()
        return {
            "text": text,
            "tool_calls": reply.get("tool_calls"),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


def _tool_call(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


@pytest.fixture
def fake_llm(monkeypatch):
    def install(replies):
        fake = FakeLLM(replies)
        from app.services.ai.llm_service import llm_service

        monkeypatch.setattr(llm_service, "generate_response_with_tools", fake)
        return fake

    return install


def _events(response) -> list[tuple[str, dict]]:
    out = []
    for block in response.text.split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event:
            out.append((event, data))
    return out


def _new_session(client) -> str:
    response = client.post(f"{BASE}/sessions", json={})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _send(client, session_id, content="hi", **extra):
    return client.post(
        f"{BASE}/sessions/{session_id}/messages",
        json={"content": content, "timezone": "UTC", **extra},
    )


def _seed_activity(db_session, org_id, workspace_id, *, statuses=("completed", "failed")):
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        original_filename="billing-calls.csv",
        total_rows=4,
        status="completed",
    )
    db_session.add(call_import)
    db_session.flush()
    for status in statuses:
        db_session.add(CallImportEvaluation(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org_id,
            workspace_id=workspace_id,
            selected_metric_ids=[],
            status=status,
            total_rows=4,
            completed_rows=4 if status == "completed" else 1,
            failed_rows=0 if status == "completed" else 3,
            created_at=datetime.now(timezone.utc),
        ))
    db_session.commit()
    return call_import


# --- readiness ----------------------------------------------------------------


def test_status_requires_an_llm(authenticated_client):
    body = authenticated_client.get(f"{BASE}/status").json()
    assert body["ready"] is False
    assert body["reasons"][0]["code"] == "no_llm"
    assert body["tools"] == []


def test_status_ready_with_default_provider(authenticated_client, ai_provider):
    body = authenticated_client.get(f"{BASE}/status").json()
    assert body["ready"] is True, body
    assert body["model"] == "gpt-4o-mini"
    assert body["credential_name"] == "Primary"
    assert "get_evaluation_activity" in body["tools"]


def test_send_refused_until_llm_configured(authenticated_client, fake_llm):
    fake = fake_llm([])
    session_id = _new_session(authenticated_client)
    response = _send(authenticated_client, session_id)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "copilot_not_ready"
    assert fake.calls == []


# --- sessions -----------------------------------------------------------------


def test_sessions_are_private_and_paginated(authenticated_client, db_session, org_id, default_workspace):
    ids = [_new_session(authenticated_client) for _ in range(3)]
    other_user = User(id=uuid4(), email="someone@example.com", name="Other", is_active=True)
    db_session.add(other_user)
    db_session.flush()
    theirs = store.create_session(
        db_session, organization_id=org_id, workspace_id=default_workspace.id, user_id=other_user.id
    )

    page1 = authenticated_client.get(f"{BASE}/sessions", params={"limit": 2}).json()
    assert len(page1["items"]) == 2 and page1["next_cursor"]
    page2 = authenticated_client.get(
        f"{BASE}/sessions", params={"limit": 2, "cursor": page1["next_cursor"]}
    ).json()
    listed = [s["id"] for s in page1["items"] + page2["items"]]
    assert sorted(listed) == sorted(ids) and page2["next_cursor"] is None

    assert authenticated_client.get(f"{BASE}/sessions/{theirs.id}").status_code == 404
    assert _send(authenticated_client, theirs.id).status_code == 404

    archived = authenticated_client.patch(f"{BASE}/sessions/{ids[0]}", json={"status": "archived"})
    assert archived.json()["status"] == "archived"
    assert authenticated_client.delete(f"{BASE}/sessions/{ids[1]}").status_code == 204
    assert authenticated_client.get(f"{BASE}/sessions/{ids[1]}").status_code == 404


# --- turns --------------------------------------------------------------------


def test_turn_streams_tool_call_and_answer(
    authenticated_client, ai_provider, turn_db, fake_llm, db_session, org_id, default_workspace
):
    _seed_activity(db_session, org_id, default_workspace.id)
    fake = fake_llm([
        {"text": "", "tool_calls": [_tool_call("get_evaluation_activity", {"period": "this_week"})]},
        {"text": "You ran 2 evaluations this week: 1 completed, 1 failed."},
    ])
    session_id = _new_session(authenticated_client)
    response = _send(
        authenticated_client,
        session_id,
        "How many evals ran this week?",
        client_message_id=str(uuid4()),
        page_context={"route": "/call-imports", "entity_type": "call_import_list"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _events(response)
    kinds = [e for e, _ in events]
    assert kinds[0] == "turn_started" and kinds[-1] == "done"
    assert ("tool_call", {"id": "call_1", "name": "get_evaluation_activity"}) in events
    assert any(e == "tool_result" and d["status"] == "ok" for e, d in events)
    streamed = "".join(d["text"] for e, d in events if e == "token")
    assert streamed == "You ran 2 evaluations this week: 1 completed, 1 failed."
    assert events[-1][1]["status"] == "complete"

    # The tool result the model saw: exact counts for this workspace.
    tool_message = fake.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    result = json.loads(tool_message["content"])
    assert result["total"] == 2
    assert result["by_status"] == {"completed": 1, "failed": 1}
    assert result["range"]["period"] == "this_week"
    assert {i["link"].split("/")[1] for i in result["items"]} == {"call-imports"}
    # Page context reaches the system prompt as data.
    assert "/call-imports" in fake.calls[0]["messages"][0]["content"]

    messages = authenticated_client.get(f"{BASE}/sessions/{session_id}/messages").json()["items"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["status"] == "complete"
    assert messages[1]["content"] == streamed
    assert [c["name"] for c in messages[1]["tool_calls"]] == ["get_evaluation_activity"]
    session = authenticated_client.get(f"{BASE}/sessions/{session_id}").json()
    assert session["title"] == "How many evals ran this week?"
    assert session["message_count"] == 2


def test_activity_never_counts_other_workspaces(db_session, org_id, default_workspace, seed_org):
    other = Workspace(organization_id=org_id, name="Other", slug="other", is_default=False)
    db_session.add(other)
    db_session.commit()
    _seed_activity(db_session, org_id, default_workspace.id, statuses=("completed",))
    _seed_activity(db_session, org_id, other.id, statuses=("completed", "failed", "running"))

    ctx = ToolContext(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        user_id=uuid4(),
        capabilities=frozenset(ALL_CAPABILITIES),
        timezone="UTC",
        session_id=uuid4(),
        llm=LLMChoice(provider="openai", model="gpt-4o-mini", credential_id=None),
    )
    result = execute(ctx, "get_evaluation_activity", {"period": "today"}, session_factory=lambda: Session(bind=db_session.connection(), join_transaction_mode="create_savepoint"))
    data = json.loads(result.content)
    assert result.status == "ok", result.content
    assert data["total"] == 1 and data["by_status"] == {"completed": 1}

    failed_only = json.loads(execute(
        ctx, "get_evaluation_activity", {"period": "today", "statuses": ["failed"]},
        session_factory=lambda: Session(bind=db_session.connection(), join_transaction_mode="create_savepoint"),
    ).content)
    assert failed_only["items"] == [] and failed_only["total"] == 1


def test_list_agents_tool_is_workspace_scoped(db_session, org_id, default_workspace, make_agent):
    make_agent(name="Billing bot", agent_id="111111")
    make_agent(name="Sales bot", agent_id="222222")
    ctx = ToolContext(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        user_id=uuid4(),
        capabilities=frozenset({"sim.view"}),
        timezone="UTC",
        session_id=uuid4(),
        llm=LLMChoice(provider="openai", model="m", credential_id=None),
    )
    data = json.loads(execute(ctx, "list_agents", {"query": "billing"}, session_factory=lambda: Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")).content)
    assert data["total"] == 1 and data["agents"][0]["name"] == "Billing bot"
    other_ws = ToolContext(**{**ctx.__dict__, "workspace_id": uuid4()})
    assert json.loads(execute(other_ws, "list_agents", {}, session_factory=lambda: Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")).content)["total"] == 0
    missing = execute(ctx, "get_agent", {"agent": "999999"}, session_factory=lambda: Session(bind=db_session.connection(), join_transaction_mode="create_savepoint"))
    assert missing.status == "error" and "No agent" in missing.content


def test_retry_with_same_client_id_runs_once(authenticated_client, ai_provider, turn_db, fake_llm):
    fake = fake_llm([{"text": "Hello!"}])
    session_id = _new_session(authenticated_client)
    client_id = str(uuid4())
    first = _events(_send(authenticated_client, session_id, client_message_id=client_id))
    second = _events(_send(authenticated_client, session_id, client_message_id=client_id))
    assert len(fake.calls) == 1
    assert second[0][1]["replayed"] is True
    assert second[0][1]["message_id"] == first[0][1]["message_id"]
    assert second[-1][1]["status"] == "complete"


def test_provider_error_saves_friendly_failure(authenticated_client, ai_provider, turn_db, fake_llm):
    fake_llm([RuntimeError("LLM tool generation failed: 401 Unauthorized")])
    session_id = _new_session(authenticated_client)
    events = _events(_send(authenticated_client, session_id))
    error = next(d for e, d in events if e == "error")
    assert "API key" in error["message"]
    assert events[-1][1]["status"] == "failed"
    reply = authenticated_client.get(f"{BASE}/sessions/{session_id}/messages").json()["items"][-1]
    assert reply["status"] == "failed" and "API key" in reply["error"]


def test_last_round_offers_no_tools(authenticated_client, ai_provider, turn_db, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "COPILOT_MAX_TOOL_ROUNDS", 1)
    fake = fake_llm([
        {"text": "", "tool_calls": [_tool_call("list_agents", {})]},
        {"text": "There are no agents yet."},
    ])
    session_id = _new_session(authenticated_client)
    events = _events(_send(authenticated_client, session_id))
    assert events[-1][1]["status"] == "complete"
    assert fake.calls[0]["tools"] and fake.calls[1]["tools"] == []


def test_message_too_long(authenticated_client, ai_provider, monkeypatch):
    monkeypatch.setattr(settings, "COPILOT_MAX_MESSAGE_CHARS", 10)
    session_id = _new_session(authenticated_client)
    assert _send(authenticated_client, session_id, "x" * 11).status_code == 422


# --- guards --------------------------------------------------------------------
# Route tests stub the Redis guards: other xdist workers flush the shared test
# Redis db, so state set in one request may be gone by the next. The Redis
# primitives themselves are tested back-to-back below.


def test_rate_limited_message_gets_429(authenticated_client, ai_provider, fake_llm, monkeypatch):
    fake = fake_llm([])
    monkeypatch.setattr(
        redis_state, "check_message_rate",
        lambda user_id, org_id: redis_state.RateLimitResult(False, 42, "user"),
    )
    response = _send(authenticated_client, _new_session(authenticated_client))
    assert response.status_code == 429 and response.headers["Retry-After"] == "42"
    assert fake.calls == []


def test_one_active_turn_per_user(authenticated_client, ai_provider, fake_llm, monkeypatch, db_session):
    fake = fake_llm([])
    monkeypatch.setattr(redis_state, "acquire_turn_lock", lambda user_id, message_id: False)
    session_id = _new_session(authenticated_client)
    response = _send(authenticated_client, session_id)
    assert response.status_code == 409 and fake.calls == []
    # Nothing was written for the refused message.
    assert db_session.query(CopilotMessage).filter(CopilotMessage.session_id == UUID(session_id)).count() == 0


def test_daily_token_budget(authenticated_client, ai_provider, fake_llm, monkeypatch):
    fake_llm([])
    monkeypatch.setattr(redis_state, "org_token_budget_exhausted", lambda org_id: True)
    response = _send(authenticated_client, _new_session(authenticated_client))
    assert response.status_code == 429 and "budget" in response.json()["detail"]


def test_redis_guard_primitives(redis_available, monkeypatch):
    monkeypatch.setattr(settings, "COPILOT_USER_MESSAGES_PER_MINUTE", 1)
    user, org = uuid4(), uuid4()
    assert redis_state.check_message_rate(user, org).allowed
    limited = redis_state.check_message_rate(user, org)
    assert not limited.allowed and limited.scope == "user" and 0 < limited.retry_after_seconds <= 60

    first, second = uuid4(), uuid4()
    assert redis_state.acquire_turn_lock(user, first)
    assert not redis_state.acquire_turn_lock(user, second)
    redis_state.release_turn_lock(user, second)  # not the owner: no effect
    assert not redis_state.acquire_turn_lock(user, second)
    redis_state.release_turn_lock(user, first)
    assert redis_state.acquire_turn_lock(user, second)


def test_redis_down_fails_open(monkeypatch):
    import redis as redis_lib

    class Down:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise redis_lib.RedisError("down")
            return fail

    monkeypatch.setattr(redis_state, "_redis", Down())
    assert redis_state.check_message_rate(uuid4(), uuid4()).allowed
    assert redis_state.acquire_turn_lock(uuid4(), uuid4())
    assert not redis_state.org_token_budget_exhausted(uuid4())
    assert not redis_state.is_cancelled(uuid4())
    assert redis_state.read_snapshots([uuid4()]) == {}


def test_cancel_stops_turn(db_session, org_id, default_workspace, turn_db, fake_llm, monkeypatch):
    fake = fake_llm([{"text": "never streamed"}])
    monkeypatch.setattr(redis_state, "is_cancelled", lambda message_id: True)
    user = User(id=uuid4(), email="c@example.com", name="C", is_active=True)
    db_session.add(user)
    db_session.flush()
    session = store.create_session(
        db_session, organization_id=org_id, workspace_id=default_workspace.id, user_id=user.id
    )
    rows = store.begin_turn(db_session, session, content="hi", client_message_id=None, page_context=None)
    events: list = []
    status = run_turn(
        TurnInput(
            session_id=session.id,
            user_message_id=rows.user_message.id,
            user_seq=rows.user_message.seq,
            assistant_message_id=rows.assistant_message.id,
            organization_id=org_id,
            workspace_id=default_workspace.id,
            user_id=user.id,
            capabilities=frozenset(ALL_CAPABILITIES),
            timezone="UTC",
            page_context=None,
            llm=LLMChoice(provider="openai", model="gpt-4o-mini", credential_id=None),
        ),
        lambda e, d: events.append((e, d)),
    )
    assert status == "cancelled" and fake.calls == []
    assert events[-1] == ("done", {**events[-1][1], "status": "cancelled"})
    db_session.expire_all()
    assert db_session.get(CopilotMessage, rows.assistant_message.id).status == "cancelled"


def test_cancel_mid_stream_keeps_partial_text(db_session, org_id, default_workspace, turn_db, fake_llm, monkeypatch):
    fake_llm([{"text": "partial answer that keeps going"}])
    checks = {"n": 0}

    def cancelled_after_first_chunk(message_id):
        checks["n"] += 1
        return checks["n"] > 2  # round start, chunk 1 pass; chunk 2 cancels

    monkeypatch.setattr(redis_state, "is_cancelled", cancelled_after_first_chunk)
    monkeypatch.setattr("app.services.copilot.turn.CANCEL_CHECK_INTERVAL_SECONDS", 0)
    user = User(id=uuid4(), email="m@example.com", name="M", is_active=True)
    db_session.add(user)
    db_session.flush()
    session = store.create_session(
        db_session, organization_id=org_id, workspace_id=default_workspace.id, user_id=user.id
    )
    rows = store.begin_turn(db_session, session, content="hi", client_message_id=None, page_context=None)
    status = run_turn(
        TurnInput(
            session_id=session.id,
            user_message_id=rows.user_message.id,
            user_seq=rows.user_message.seq,
            assistant_message_id=rows.assistant_message.id,
            organization_id=org_id,
            workspace_id=default_workspace.id,
            user_id=user.id,
            capabilities=frozenset(ALL_CAPABILITIES),
            timezone="UTC",
            page_context=None,
            llm=LLMChoice(provider="openai", model="gpt-4o-mini", credential_id=None),
        ),
        lambda e, d: None,
    )
    assert status == "cancelled"
    db_session.expire_all()
    saved = db_session.get(CopilotMessage, rows.assistant_message.id)
    assert saved.content == "parti"  # the first streamed chunk survives the cancel


# --- history ------------------------------------------------------------------


def test_history_replays_recent_tool_rounds_and_drops_unanswered(db_session, org_id, default_workspace):
    user = User(id=uuid4(), email="h@example.com", name="H", is_active=True)
    db_session.add(user)
    db_session.flush()
    session = store.create_session(
        db_session, organization_id=org_id, workspace_id=default_workspace.id, user_id=user.id
    )

    def turn(question, answer, status="complete", steps=None):
        rows = store.begin_turn(db_session, session, content=question, client_message_id=None, page_context=None)
        store.finish_turn(
            db_session, rows.assistant_message.id, content=answer, steps=steps or [], status=status,
            error=None, model="m", prompt_tokens=0, completion_tokens=0, latency_ms=1, session_id=session.id,
        )
        db_session.refresh(session)
        return rows

    turn("q1", "a1", steps=[{"text": "", "calls": [
        {"id": "c1", "name": "list_agents", "arguments": "{}", "status": "ok", "content": '{"total": 0}'}
    ]}])
    turn("lost", "", status="failed")
    current = store.begin_turn(db_session, session, content="q3", client_message_id=None, page_context=None)

    history = store.history_for_llm(db_session, session.id, up_to_seq=current.user_message.seq, limit=20)
    assert [m["role"] for m in history] == ["user", "assistant", "tool", "assistant", "user"]
    assert history[1]["tool_calls"][0]["function"]["name"] == "list_agents"
    assert history[-1]["content"] == "q3"
    assert "lost" not in [m.get("content") for m in history]


def test_stale_streaming_reply_reads_as_interrupted(authenticated_client, db_session, ai_provider):
    session_id = _new_session(authenticated_client)
    session = db_session.get(CopilotSession, UUID(session_id))
    rows = store.begin_turn(db_session, session, content="hi", client_message_id=None, page_context=None)
    rows.assistant_message.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()
    reply = authenticated_client.get(f"{BASE}/sessions/{session_id}/messages").json()["items"][-1]
    assert reply["status"] == "interrupted"
