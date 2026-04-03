"""API tests for scenario routes."""


def test_create_and_list_scenarios(authenticated_client):
    payload = {
        "name": "Billing Scenario",
        "description": "Handle billing disputes",
        "required_info": {"account_number": "string"},
    }
    create_response = authenticated_client.post("/api/v1/scenarios", json=payload)

    assert create_response.status_code == 201
    assert create_response.json()["name"] == "Billing Scenario"

    list_response = authenticated_client.get("/api/v1/scenarios")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_update_scenario(authenticated_client):
    create_response = authenticated_client.post(
        "/api/v1/scenarios",
        json={"name": "Update Scenario", "required_info": {}},
    )
    scenario_id = create_response.json()["id"]

    update_response = authenticated_client.put(
        f"/api/v1/scenarios/{scenario_id}",
        json={"description": "Updated description", "required_info": {"foo": "bar"}},
    )

    assert update_response.status_code == 200
    body = update_response.json()
    assert body["description"] == "Updated description"
    assert body["required_info"] == {"foo": "bar"}


def test_delete_scenario_no_dependencies(authenticated_client):
    create_response = authenticated_client.post(
        "/api/v1/scenarios",
        json={"name": "Delete Scenario", "required_info": {}},
    )
    scenario_id = create_response.json()["id"]

    delete_response = authenticated_client.delete(f"/api/v1/scenarios/{scenario_id}")

    assert delete_response.status_code == 204
