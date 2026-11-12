"""Metrics API: agent_ids round-trip and validation."""


def test_create_metric_with_agent_ids(authenticated_client, make_agent):
    agent = make_agent(name="Scope Agent")
    payload = {
        "name": "Agent scoped metric",
        "metric_type": "boolean",
        "trigger": "always",
        "enabled": True,
        "agent_ids": [str(agent.id)],
    }
    response = authenticated_client.post("/api/v1/metrics", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["agent_ids"] == [str(agent.id)]
    assert body["scenario_ids"] == []


def test_update_metric_clears_agent_links(authenticated_client, make_metric, make_agent):
    agent = make_agent(name="A1")
    metric = make_metric(name="Updatable")
    create = authenticated_client.post(
        "/api/v1/metrics",
        json={
            "name": "Linked",
            "metric_type": "rating",
            "trigger": "always",
            "enabled": True,
            "agent_ids": [str(agent.id)],
        },
    )
    assert create.status_code == 201
    mid = create.json()["id"]

    cleared = authenticated_client.put(f"/api/v1/metrics/{mid}", json={"agent_ids": []})
    assert cleared.status_code == 200
    assert cleared.json()["agent_ids"] == []


def test_child_metric_rejects_agent_ids(authenticated_client, make_metric):
    parent = make_metric(name="Parent cat", selection_mode="single_choice")
    payload = {
        "name": "Bad child",
        "metric_type": "boolean",
        "trigger": "always",
        "enabled": True,
        "parent_metric_id": str(parent.id),
        "agent_ids": [str(parent.id)],
    }
    response = authenticated_client.post("/api/v1/metrics", json=payload)
    assert response.status_code == 400
