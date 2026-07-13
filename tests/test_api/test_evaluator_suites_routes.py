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
    s1 = make_scenario(name="Scenario One")
    s2 = make_scenario(name="Scenario Two")

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
    scenario = make_scenario()
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
    s1 = make_scenario(name="A")
    s2 = make_scenario(name="B")
    s3 = make_scenario(name="C")

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


def test_run_next_advances_round_robin(
    authenticated_client, monkeypatch, make_agent, make_persona, make_scenario
):
    from app.workers import celery_app

    agent = make_agent(call_medium="web_call", call_type="inbound")
    persona = make_persona()
    s1 = make_scenario(name="First")
    s2 = make_scenario(name="Second")

    create = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "agent_id": str(agent.id),
            "persona_id": str(persona.id),
            "scenario_ids": [str(s1.id), str(s2.id)],
        },
    )
    suite_id = create.json()["id"]

    monkeypatch.setattr(
        celery_app.run_evaluator_task,
        "delay",
        lambda *_a, **_k: _FakeTaskResult("task-1"),
    )

    first = authenticated_client.post(f"/api/v1/evaluator-suites/{suite_id}/run-next", json={})
    assert first.status_code == 200
    assert first.json()["combination_index"] == 0

    second = authenticated_client.post(f"/api/v1/evaluator-suites/{suite_id}/run-next", json={})
    assert second.status_code == 200
    assert second.json()["combination_index"] == 1

    suite = authenticated_client.get(f"/api/v1/evaluator-suites/{suite_id}").json()
    assert suite["round_robin_index"] == 2


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
