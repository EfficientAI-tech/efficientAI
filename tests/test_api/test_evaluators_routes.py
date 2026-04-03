"""API tests for evaluator routes."""


class _FakeTaskResult:
    def __init__(self, task_id):
        self.id = task_id


def test_create_evaluator_success(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent()
    persona = make_persona()
    scenario = make_scenario(agent_id=agent.id)
    payload = {
        "name": "Baseline Evaluator",
        "agent_id": str(agent.id),
        "persona_id": str(persona.id),
        "scenario_id": str(scenario.id),
        "tags": ["baseline"],
    }

    response = authenticated_client.post("/api/v1/evaluators", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Baseline Evaluator"
    assert body["agent_id"] == str(agent.id)


def test_list_and_get_evaluator(authenticated_client, make_evaluator):
    evaluator = make_evaluator(evaluator_id="345678", name="List Me")

    list_response = authenticated_client.get("/api/v1/evaluators")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/evaluators/{evaluator.evaluator_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == str(evaluator.id)


def test_run_evaluators_returns_task_ids(
    authenticated_client, monkeypatch, make_evaluator
):
    from app.workers import celery_app

    evaluator = make_evaluator()
    counter = {"i": 0}

    def _fake_delay(*_args, **_kwargs):
        counter["i"] += 1
        return _FakeTaskResult(f"task-{counter['i']}")

    monkeypatch.setattr(celery_app.run_evaluator_task, "delay", _fake_delay)

    payload = {"evaluator_ids": [str(evaluator.id), str(evaluator.id)]}
    response = authenticated_client.post("/api/v1/evaluators/run", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["task_ids"] == ["task-1", "task-2"]
    assert len(body["evaluator_results"]) == 2
