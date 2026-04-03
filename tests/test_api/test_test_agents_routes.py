"""API tests for test-agents routes."""


def test_create_list_get_test_agent_conversation(
    authenticated_client,
    monkeypatch,
    make_agent,
    make_persona,
    make_scenario,
    make_voice_bundle,
    make_test_agent_conversation,
):
    from app.api.v1.routes import test_agents as test_agents_routes

    agent = make_agent()
    persona = make_persona()
    scenario = make_scenario(agent_id=agent.id)
    voice_bundle = make_voice_bundle()

    created_conversation = make_test_agent_conversation(
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        voice_bundle_id=voice_bundle.id,
    )

    monkeypatch.setattr(
        test_agents_routes.test_agent_service,
        "create_conversation",
        lambda **_kwargs: created_conversation,
    )

    payload = {
        "agent_id": str(agent.id),
        "persona_id": str(persona.id),
        "scenario_id": str(scenario.id),
        "voice_bundle_id": str(voice_bundle.id),
        "conversation_metadata": {"source": "test"},
    }
    create_response = authenticated_client.post("/api/v1/test-agents/conversations", json=payload)
    assert create_response.status_code == 201

    list_response = authenticated_client.get("/api/v1/test-agents/conversations")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(
        f"/api/v1/test-agents/conversations/{created_conversation.id}"
    )
    assert get_response.status_code == 200
    assert get_response.json()["id"] == str(created_conversation.id)


def test_start_update_end_delete_conversation(
    authenticated_client,
    monkeypatch,
    make_agent,
    make_persona,
    make_scenario,
    make_voice_bundle,
    make_test_agent_conversation,
):
    from app.api.v1.routes import test_agents as test_agents_routes

    agent = make_agent()
    persona = make_persona()
    scenario = make_scenario(agent_id=agent.id)
    voice_bundle = make_voice_bundle()
    conversation = make_test_agent_conversation(
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        voice_bundle_id=voice_bundle.id,
    )

    monkeypatch.setattr(
        test_agents_routes.test_agent_service,
        "start_conversation",
        lambda **_kwargs: conversation,
    )
    monkeypatch.setattr(
        test_agents_routes.test_agent_service,
        "end_conversation",
        lambda **_kwargs: conversation,
    )

    start_response = authenticated_client.post(
        f"/api/v1/test-agents/conversations/{conversation.id}/start"
    )
    assert start_response.status_code == 200

    update_response = authenticated_client.put(
        f"/api/v1/test-agents/conversations/{conversation.id}",
        json={"status": "completed", "full_transcript": "final transcript"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["full_transcript"] == "final transcript"

    end_response = authenticated_client.post(
        f"/api/v1/test-agents/conversations/{conversation.id}/end"
    )
    assert end_response.status_code == 200

    delete_response = authenticated_client.delete(f"/api/v1/test-agents/conversations/{conversation.id}")
    assert delete_response.status_code == 204
