"""Tool connections API: CRUD, write-only secrets, agent links and the agent tool catalog."""

from uuid import uuid4

HTTP_CONNECTION = {
    "name": "Orders API",
    "connection_type": "http",
    "config": {
        "base_url": "https://api.example.com",
        "tools": [
            {"name": "get_order", "method": "GET", "path": "/orders/{order_id}"},
            {"name": "refund_order", "method": "POST", "path": "/refunds"},
        ],
    },
    "secrets": {"headers": {"Authorization": "Bearer s3cret"}},
}


def _create(client, **overrides):
    response = client.post("/api/v1/tool-connections", json={**HTTP_CONNECTION, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_lists_tools_and_hides_secrets(authenticated_client):
    body = _create(authenticated_client)
    assert body["slug"] == "orders_api"
    assert body["secret_keys"] == ["headers.Authorization"]
    assert "s3cret" not in str(body)
    assert body["last_error"] is None
    assert [(t["exposed_name"], t["side_effect"]) for t in body["tools"]] == [
        ("orders_api__get_order", "read"),
        ("orders_api__refund_order", "write"),
    ]
    second = _create(authenticated_client)
    assert second["slug"] == "orders_api_2"


def test_update_merges_secrets_and_mode(authenticated_client):
    created = _create(authenticated_client)
    response = authenticated_client.patch(
        f"/api/v1/tool-connections/{created['id']}",
        json={
            "simulation_mode": "live",
            "secrets": {"headers": {"Authorization": "", "X-Api-Key": "k"}},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["simulation_mode"] == "live"
    assert response.json()["secret_keys"] == ["headers.X-Api-Key"]


def test_invalid_configs_rejected(authenticated_client):
    bad_tools = authenticated_client.post(
        "/api/v1/tool-connections",
        json={**HTTP_CONNECTION, "config": {"tools": []}},
    )
    assert bad_tools.status_code == 400
    stdio = authenticated_client.post(
        "/api/v1/tool-connections",
        json={
            "name": "Local",
            "connection_type": "mcp",
            "config": {"transport": "stdio", "command": "npx"},
        },
    )
    assert stdio.status_code == 400
    assert "disabled" in stdio.json()["detail"]


def test_agent_links_and_catalog(authenticated_client, make_agent):
    agent = make_agent(name="Support")
    connection = _create(authenticated_client)
    put = authenticated_client.put(
        f"/api/v1/tool-connections/agents/{agent.id}/links",
        json={"links": [{"tool_connection_id": connection["id"], "enabled_tools": ["get_order"]}]},
    )
    assert put.status_code == 200, put.text

    links = authenticated_client.get(f"/api/v1/tool-connections/agents/{agent.id}/links").json()
    assert links == [{"tool_connection_id": connection["id"], "enabled_tools": ["get_order"]}]
    catalog = authenticated_client.get(f"/api/v1/tool-connections/agents/{agent.id}/catalog")
    assert catalog.status_code == 200, catalog.text
    assert [(t["name"], t["simulation_behavior"]) for t in catalog.json()] == [
        ("orders_api__get_order", "live")
    ]
    listed = authenticated_client.get("/api/v1/tool-connections").json()
    assert listed[0]["agent_count"] == 1

    unknown = authenticated_client.put(
        f"/api/v1/tool-connections/agents/{agent.id}/links",
        json={"links": [{"tool_connection_id": str(uuid4())}]},
    )
    assert unknown.status_code == 400

    deleted = authenticated_client.delete(f"/api/v1/tool-connections/{connection['id']}")
    assert deleted.status_code == 204
    assert (
        authenticated_client.get(f"/api/v1/tool-connections/agents/{agent.id}/links").json() == []
    )
