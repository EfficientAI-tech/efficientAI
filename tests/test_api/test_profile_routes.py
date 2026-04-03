"""API tests for profile routes."""


def test_get_and_update_profile(authenticated_client, user_context):
    get_response = authenticated_client.get("/api/v1/profile")
    assert get_response.status_code == 200
    assert get_response.json()["email"] == user_context["user"].email

    update_response = authenticated_client.put(
        "/api/v1/profile",
        json={"name": "Updated Owner", "first_name": "Updated", "last_name": "User"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Updated Owner"


def test_get_and_update_preferences(authenticated_client, user_context, make_agent):
    agent = make_agent()

    get_response = authenticated_client.get("/api/v1/profile/preferences")
    assert get_response.status_code == 200
    assert get_response.json()["default_agent_id"] is None

    update_response = authenticated_client.put(
        "/api/v1/profile/preferences",
        json={"default_agent_id": str(agent.id)},
    )
    assert update_response.status_code == 200
    assert update_response.json()["default_agent_id"] == str(agent.id)
