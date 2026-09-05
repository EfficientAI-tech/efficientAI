"""API tests for evaluator suite persona grid and persona membership routes."""

import importlib
import types


class _FakeTaskResult:
    def __init__(self, task_id):
        self.id = task_id


def _patch_run_evaluator_task_delay(monkeypatch, delay_fn):
    celery_app_module = importlib.import_module("app.workers.celery_app")
    monkeypatch.setattr(
        celery_app_module,
        "run_evaluator_task",
        types.SimpleNamespace(delay=delay_fn),
    )


def test_create_evaluator_suite_with_persona_ids_cartesian_grid(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent()
    persona_a = make_persona(name="Persona A")
    persona_b = make_persona(name="Persona B")
    s1 = make_scenario(name="Scenario One", agent_id=agent.id)
    s2 = make_scenario(name="Scenario Two", agent_id=agent.id)

    response = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "name": "Grid Suite",
            "agent_id": str(agent.id),
            "persona_ids": [str(persona_a.id), str(persona_b.id)],
            "scenario_ids": [str(s1.id), str(s2.id)],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["combination_count"] == 4
    assert len(body["combinations"]) == 4
    assert len(body["persona_ids"]) == 2
    assert len(body["personas"]) == 2
    pairs = {(c["persona_id"], c["scenario_id"]) for c in body["combinations"]}
    assert len(pairs) == 4


def test_create_evaluator_suite_backward_compat_persona_id(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent()
    persona = make_persona()
    scenario = make_scenario(agent_id=agent.id)

    response = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "agent_id": str(agent.id),
            "persona_id": str(persona.id),
            "scenario_ids": [str(scenario.id)],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["combination_count"] == 1
    assert body["persona_ids"] == [str(persona.id)]


def test_add_persona_expands_grid(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent()
    persona_a = make_persona(name="Persona A")
    persona_b = make_persona(name="Persona B")
    s1 = make_scenario(name="S1", agent_id=agent.id)
    s2 = make_scenario(name="S2", agent_id=agent.id)

    create = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "agent_id": str(agent.id),
            "persona_id": str(persona_a.id),
            "scenario_ids": [str(s1.id), str(s2.id)],
        },
    )
    suite_id = create.json()["id"]
    assert create.json()["combination_count"] == 2

    added = authenticated_client.post(
        f"/api/v1/evaluator-suites/{suite_id}/personas",
        json={"persona_ids": [str(persona_b.id)]},
    )
    assert added.status_code == 200
    body = added.json()
    assert body["combination_count"] == 4
    assert len(body["persona_ids"]) == 2


def test_replace_last_persona_updates_children(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent()
    persona_a = make_persona(name="Persona A")
    persona_b = make_persona(name="Persona B")
    scenario = make_scenario(agent_id=agent.id)

    create = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "agent_id": str(agent.id),
            "persona_id": str(persona_a.id),
            "scenario_ids": [str(scenario.id)],
        },
    )
    suite_id = create.json()["id"]

    replaced = authenticated_client.put(
        f"/api/v1/evaluator-suites/{suite_id}/personas",
        json={"persona_ids": [str(persona_b.id)]},
    )
    assert replaced.status_code == 200
    body = replaced.json()
    assert body["combination_count"] == 1
    assert body["persona_id"] == str(persona_b.id)
    assert body["combinations"][0]["persona_id"] == str(persona_b.id)


def test_remove_last_persona_rejected(
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

    response = authenticated_client.delete(
        f"/api/v1/evaluator-suites/{suite_id}/personas/{persona.id}"
    )
    assert response.status_code == 400


def test_add_scenario_to_multi_persona_suite(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent()
    persona_a = make_persona(name="Persona A")
    persona_b = make_persona(name="Persona B")
    s1 = make_scenario(name="S1", agent_id=agent.id)
    s2 = make_scenario(name="S2", agent_id=agent.id)

    create = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "agent_id": str(agent.id),
            "persona_ids": [str(persona_a.id), str(persona_b.id)],
            "scenario_ids": [str(s1.id)],
        },
    )
    suite_id = create.json()["id"]
    assert create.json()["combination_count"] == 2

    added = authenticated_client.post(
        f"/api/v1/evaluator-suites/{suite_id}/scenarios",
        json={"scenario_ids": [str(s2.id)]},
    )
    assert added.status_code == 200
    assert added.json()["combination_count"] == 4


def test_remove_scenario_deletes_all_persona_rows(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent()
    persona_a = make_persona(name="Persona A")
    persona_b = make_persona(name="Persona B")
    s1 = make_scenario(name="S1", agent_id=agent.id)
    s2 = make_scenario(name="S2", agent_id=agent.id)

    create = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "agent_id": str(agent.id),
            "persona_ids": [str(persona_a.id), str(persona_b.id)],
            "scenario_ids": [str(s1.id), str(s2.id)],
        },
    )
    suite_id = create.json()["id"]
    assert create.json()["combination_count"] == 4

    removed = authenticated_client.delete(
        f"/api/v1/evaluator-suites/{suite_id}/scenarios/{s2.id}"
    )
    assert removed.status_code == 200
    body = removed.json()
    assert body["combination_count"] == 2
    assert all(c["scenario_id"] == str(s1.id) for c in body["combinations"])


def test_round_robin_visits_all_persona_scenario_combinations(
    authenticated_client, make_agent, make_persona, make_scenario
):
    agent = make_agent(call_medium="phone_call", call_type="inbound")
    persona_a = make_persona(name="Persona A")
    persona_b = make_persona(name="Persona B")
    s1 = make_scenario(name="S1", agent_id=agent.id)
    s2 = make_scenario(name="S2", agent_id=agent.id)

    create = authenticated_client.post(
        "/api/v1/evaluator-suites",
        json={
            "agent_id": str(agent.id),
            "persona_ids": [str(persona_a.id), str(persona_b.id)],
            "scenario_ids": [str(s1.id), str(s2.id)],
        },
    )
    suite_id = create.json()["id"]

    seen = set()
    for _ in range(4):
        resp = authenticated_client.post(f"/api/v1/evaluator-suites/{suite_id}/choose-next")
        assert resp.status_code == 200
        data = resp.json()
        seen.add((data["persona_id"], data["scenario_id"]))

    assert len(seen) == 4
