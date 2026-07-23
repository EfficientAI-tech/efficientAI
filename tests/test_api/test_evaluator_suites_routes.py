"""API tests for evaluator suite routes."""

from uuid import uuid4


class _FakeTaskResult:
    def __init__(self, task_id):
        self.id = task_id


def test_create_evaluator_suite(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent()
    persona = make_persona()
    s1 = make_scenario(name="Scenario One", agent_id=agent.id)
    s2 = make_scenario(name="Scenario Two", agent_id=agent.id)

    payload = {
        "name": "Billing Suite",
        "agent_id": str(agent.id),
        "persona_id": str(persona.id),
        "scenario_ids": [str(s1.id), str(s2.id)],
        "default_runs_per_combination": 2,
    }
    response = authenticated_client.post("/api/v1/evaluator-suites", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Billing Suite"
    assert body["combination_count"] == 2
    assert len(body["combinations"]) == 2


def test_list_and_get_evaluator_suite(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent()
    persona = make_persona()
    scenario = make_scenario(agent_id=agent.id)
    create = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "agent_id": str(agent.id),
            "persona_id": str(persona.id),
            "scenario_ids": [str(scenario.id)],
        },
    )
    suite_id = create.json()["id"]

    list_response = authenticated_client.get("/api/v1/evaluator-suites")
    assert list_response.status_code == 200
    assert any(s["id"] == suite_id for s in list_response.json())

    get_response = authenticated_client.get(f"/api/v1/evaluator-suites/{suite_id}")
    assert get_response.status_code == 200
    assert get_response.json()["combination_count"] == 1


def test_run_evaluator_suite_expands_runs(
    authenticated_client, monkeypatch, make_agent, make_persona, make_scenario
):
    from app.workers import celery_app

    agent = make_agent(call_medium="web_call")
    persona = make_persona()
    s1 = make_scenario(name="A", agent_id=agent.id)
    s2 = make_scenario(name="B", agent_id=agent.id)
    s3 = make_scenario(name="C", agent_id=agent.id)

    create = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "agent_id": str(agent.id),
            "persona_id": str(persona.id),
            "scenario_ids": [str(s1.id), str(s2.id), str(s3.id)],
        },
    )
    suite_id = create.json()["id"]

    counter = {"i": 0}

    def _fake_delay(*_args, **_kwargs):
        counter["i"] += 1
        return _FakeTaskResult(f"task-{counter['i']}")

    monkeypatch.setattr(celery_app.run_evaluator_task, "delay", _fake_delay)

    run_response = authenticated_client.post(
        f"/api/v1/evaluator-suites/{suite_id}/run",
        json={"runs_per_combination": 5},
    )
    assert run_response.status_code == 200
    body = run_response.json()
    assert body["total_runs"] == 15
    assert len(body["task_ids"]) == 15


def test_choose_next_advances_round_robin(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent(call_medium="phone_call", call_type="inbound")
    persona = make_persona()
    s1 = make_scenario(name="First", agent_id=agent.id)
    s2 = make_scenario(name="Second", agent_id=agent.id)

    create = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "agent_id": str(agent.id),
            "persona_id": str(persona.id),
            "scenario_ids": [str(s1.id), str(s2.id)],
        },
    )
    suite_id = create.json()["id"]
    assert create.json()["is_active"] is True

    first = authenticated_client.post(f"/api/v1/evaluator-suites/{suite_id}/choose-next")
    assert first.status_code == 200
    assert first.json()["combination_index"] == 0

    second = authenticated_client.post(f"/api/v1/evaluator-suites/{suite_id}/choose-next")
    assert second.status_code == 200
    assert second.json()["combination_index"] == 1

    suite = authenticated_client.get(f"/api/v1/evaluator-suites/{suite_id}").json()
    assert suite["round_robin_index"] == 2

    run_next = authenticated_client.post(f"/api/v1/evaluator-suites/{suite_id}/run-next", json={})
    assert run_next.status_code == 400


def test_second_suite_inactive_until_activated(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent(call_medium="phone_call", call_type="inbound")
    persona_a = make_persona(name="Persona A")
    persona_b = make_persona(name="Persona B")
    s1 = make_scenario(name="S1", agent_id=agent.id)
    s2 = make_scenario(name="S2", agent_id=agent.id)

    first = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "name": "Suite A",
            "agent_id": str(agent.id),
            "persona_id": str(persona_a.id),
            "scenario_ids": [str(s1.id)],
        },
    )
    assert first.status_code == 201
    suite_a_id = first.json()["id"]
    assert first.json()["is_active"] is True

    second = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "name": "Suite B",
            "agent_id": str(agent.id),
            "persona_id": str(persona_b.id),
            "scenario_ids": [str(s2.id)],
        },
    )
    assert second.status_code == 201
    suite_b_id = second.json()["id"]
    assert second.json()["is_active"] is False
    assert second.json()["agent_suite_count"] == 2

    blocked = authenticated_client.post(f"/api/v1/evaluator-suites/{suite_b_id}/choose-next")
    assert blocked.status_code == 400

    activated = authenticated_client.post(f"/api/v1/evaluator-suites/{suite_b_id}/activate")
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True

    suite_a = authenticated_client.get(f"/api/v1/evaluator-suites/{suite_a_id}").json()
    assert suite_a["is_active"] is False


def test_create_suite_rejects_scenario_not_linked_to_agent(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent()
    other_agent = make_agent(name="Other Agent", agent_id="654321")
    persona = make_persona()
    linked = make_scenario(name="Linked", agent_id=agent.id)
    unlinked = make_scenario(name="Wrong agent", agent_id=other_agent.id)

    response = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "agent_id": str(agent.id),
            "persona_id": str(persona.id),
            "scenario_ids": [str(linked.id), str(unlinked.id)],
        },
    )
    assert response.status_code == 400
    assert "not linked" in response.json()["detail"].lower()


def test_inbound_evaluator_round_robin_via_service(
    db_session,
    org_id,
    default_workspace,
    make_agent,
    make_persona,
    make_scenario,
):
    from app.models.database import EvaluatorSuite
    from app.models.schemas import EvaluatorSuiteCreate
    from app.services.evaluators.evaluator_inbound_service import (
        consume_inbound_evaluator_combination,
        find_inbound_suite_for_agent,
    )
    from app.services.evaluators.evaluator_suite_service import create_evaluator_suite

    agent = make_agent(call_type="inbound", call_medium="phone_call")
    persona = make_persona()
    s1 = make_scenario(name="Inbound A", agent_id=agent.id)
    s2 = make_scenario(name="Inbound B", agent_id=agent.id)

    suite_resp = create_evaluator_suite(
        db_session,
        org_id,
        default_workspace.id,
        EvaluatorSuiteCreate(
            agent_id=agent.id,
            persona_id=persona.id,
            scenario_ids=[s1.id, s2.id],
        ),
    )
    suite = db_session.query(EvaluatorSuite).filter(EvaluatorSuite.id == suite_resp.id).one()
    found = find_inbound_suite_for_agent(db_session, agent, org_id, default_workspace.id)
    assert found is not None
    assert found.id == suite.id

    consume_inbound_evaluator_combination(db_session, found)
    consume_inbound_evaluator_combination(db_session, found)
    db_session.refresh(suite)
    assert suite.round_robin_index == 2


def test_create_custom_evaluator_blocked(authenticated_client, make_metric):
    metric = make_metric()
    response = authenticated_client.post(
        "/api/v1/evaluators",
        json={
            "name": "Custom",
            "metric_ids": [str(metric.id)],
        },
    )
    assert response.status_code == 400
