"""API tests for pre-prod LLM chat agents."""


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


def test_create_chat_agent_rejects_post_prod_eval_mode(authenticated_client, make_ai_provider):
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
    assert "pre_prod_sim" in response.json()["detail"]


def test_create_chat_agent_rejects_customer_api_connection(authenticated_client, make_ai_provider):
    cred = make_ai_provider(provider="openai")
    payload = {
        "name": "API Chat Bot",
        "language": "en",
        "description": _chat_prompt(),
        "provider_prompt": _chat_prompt(),
        "call_type": "outbound",
        "call_medium": "chat",
        "chat_connection_type": "customer_api",
        "chat_connection_config": {"api_base_url": "https://example.com"},
        "main_llm_provider": "openai",
        "main_llm_model": "gpt-4o-mini",
        "main_llm_credential_id": str(cred.id),
        "test_llm_provider": "openai",
        "test_llm_model": "gpt-4o-mini",
        "test_llm_credential_id": str(cred.id),
    }

    response = authenticated_client.post("/api/v1/agents", json=payload)

    assert response.status_code == 400
    assert "internal_llm" in response.json()["detail"]


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
