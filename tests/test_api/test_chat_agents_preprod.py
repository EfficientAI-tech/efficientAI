"""API tests for LLM chat agents (pre-prod + post-prod live connections)."""


def _chat_prompt() -> str:
    return (
        "You are a helpful support agent that answers billing questions clearly "
        "and professionally for customers."
    )


def test_create_chat_agent_preprod_internal_llm(authenticated_client, make_ai_provider):
    cred = make_ai_provider(provider="openai")
    payload = {
        "name": "Billing Chat Bot",
        "language": "en",
        "description": _chat_prompt(),
        "provider_prompt": _chat_prompt(),
        "call_type": "outbound",
        "call_medium": "chat",
        "chat_connection_type": "internal_llm",
        "chat_eval_mode": "pre_prod_sim",
        "main_llm_provider": "openai",
        "main_llm_model": "gpt-4o-mini",
        "main_llm_credential_id": str(cred.id),
        "test_llm_provider": "openai",
        "test_llm_model": "gpt-4o-mini",
        "test_llm_credential_id": str(cred.id),
    }

    response = authenticated_client.post("/api/v1/agents", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["call_medium"] == "chat"
    assert body["chat_connection_type"] == "internal_llm"
    assert body["chat_eval_mode"] == "pre_prod_sim"
    assert body["main_llm_model"] == "gpt-4o-mini"


def test_create_chat_agent_rejects_post_prod_import(authenticated_client, make_ai_provider):
    cred = make_ai_provider(provider="openai")
    payload = {
        "name": "Import Chat Bot",
        "language": "en",
        "description": _chat_prompt(),
        "provider_prompt": _chat_prompt(),
        "call_type": "outbound",
        "call_medium": "chat",
        "chat_connection_type": "internal_llm",
        "chat_eval_mode": "post_prod_import",
        "main_llm_provider": "openai",
        "main_llm_model": "gpt-4o-mini",
        "main_llm_credential_id": str(cred.id),
        "test_llm_provider": "openai",
        "test_llm_model": "gpt-4o-mini",
        "test_llm_credential_id": str(cred.id),
    }

    response = authenticated_client.post("/api/v1/agents", json=payload)

    assert response.status_code == 400
    assert "import" in response.json()["detail"].lower()


def test_create_chat_agent_customer_api_post_prod_live(authenticated_client):
    payload = {
        "name": "API Chat Bot",
        "language": "en",
        "description": _chat_prompt(),
        "provider_prompt": _chat_prompt(),
        "call_type": "outbound",
        "call_medium": "chat",
        "chat_connection_type": "customer_api",
        "chat_connection_config": {"api_base_url": "https://example.com"},
    }

    response = authenticated_client.post("/api/v1/agents", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["chat_connection_type"] == "customer_api"
    assert body["chat_eval_mode"] == "post_prod_live"


def test_create_chat_agent_provider_chat_without_test_llm(authenticated_client, make_integration):
    integration = make_integration(platform="retell")
    payload = {
        "name": "Retell Chat Bot",
        "language": "en",
        "description": _chat_prompt(),
        "provider_prompt": _chat_prompt(),
        "call_type": "outbound",
        "call_medium": "chat",
        "chat_connection_type": "provider_chat",
        "voice_ai_integration_id": str(integration.id),
        "voice_ai_agent_id": "chat-agent-abc",
    }

    response = authenticated_client.post("/api/v1/agents", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["chat_connection_type"] == "provider_chat"
    assert body["chat_eval_mode"] == "post_prod_live"
    assert body["voice_ai_agent_id"] == "chat-agent-abc"


def test_update_provider_chat_agent_persists_voice_bundle(
    authenticated_client, make_integration, make_voice_bundle
):
    integration = make_integration(platform="retell")
    bundle = make_voice_bundle()
    payload = {
        "name": "Retell Chat With Bundle",
        "language": "en",
        "description": _chat_prompt(),
        "provider_prompt": _chat_prompt(),
        "call_type": "outbound",
        "call_medium": "chat",
        "chat_connection_type": "provider_chat",
        "voice_ai_integration_id": str(integration.id),
        "voice_ai_agent_id": "chat-agent-retell-1",
    }
    created = authenticated_client.post("/api/v1/agents", json=payload)
    assert created.status_code == 201
    agent_id = created.json()["id"]
    assert created.json().get("voice_bundle_id") is None

    patch = {
        "voice_bundle_id": str(bundle.id),
        "provider_prompt": _chat_prompt(),
        "voice_ai_integration_id": str(integration.id),
        "voice_ai_agent_id": "chat-agent-retell-1",
    }
    response = authenticated_client.put(f"/api/v1/agents/{agent_id}", json=patch)
    assert response.status_code == 200
    assert response.json()["voice_bundle_id"] == str(bundle.id)

    fetched = authenticated_client.get(f"/api/v1/agents/{agent_id}")
    assert fetched.status_code == 200
    assert fetched.json()["voice_bundle_id"] == str(bundle.id)


def test_update_chat_agent_persists_llm_and_preprod_mode(authenticated_client, make_ai_provider):
    cred = make_ai_provider(provider="openai")
    create_payload = {
        "name": "Update Chat Bot",
        "language": "en",
        "description": _chat_prompt(),
        "provider_prompt": _chat_prompt(),
        "call_type": "outbound",
        "call_medium": "chat",
        "chat_connection_type": "internal_llm",
        "main_llm_provider": "openai",
        "main_llm_model": "gpt-4o-mini",
        "main_llm_credential_id": str(cred.id),
        "test_llm_provider": "openai",
        "test_llm_model": "gpt-4o-mini",
        "test_llm_credential_id": str(cred.id),
    }
    created = authenticated_client.post("/api/v1/agents", json=create_payload)
    assert created.status_code == 201
    agent_id = created.json()["id"]

    patch = {
        "main_llm_model": "gpt-4o",
        "chat_eval_mode": "post_prod_live",
    }
    response = authenticated_client.put(f"/api/v1/agents/{agent_id}", json=patch)
    assert response.status_code == 200
    body = response.json()
    assert body["main_llm_model"] == "gpt-4o"
    assert body["chat_eval_mode"] == "pre_prod_sim"
