"""API tests for agent test setup generation routes."""


def test_generate_test_prompt(authenticated_client, monkeypatch, make_ai_provider):
    from importlib import import_module

    llm_service_module = import_module("app.services.ai.llm_service")
    make_ai_provider(provider="openai")

    llm_response = (
        "You are a caller interacting with a support agent. "
        "Introduce yourself naturally and ask questions about your issue."
    )

    monkeypatch.setattr(
        llm_service_module.llm_service,
        "generate_response",
        lambda **_kwargs: {"text": llm_response},
    )

    response = authenticated_client.post(
        "/api/v1/agents/generate-test-prompt",
        json={
            "production_prompt": "You are a support agent. Greet callers and help with FAQs.",
            "agent_name": "Support Bot",
            "language": "en",
            "call_type": "inbound",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sections"] == []
    assert body["test_agent_prompt"] == llm_response
    assert "caller interacting with a support agent" in body["test_agent_prompt"]
    assert body["provider"] == "openai"


def test_generate_scenarios_from_prompt(authenticated_client, monkeypatch, make_ai_provider):
    from importlib import import_module

    llm_service_module = import_module("app.services.ai.llm_service")
    make_ai_provider(provider="openai")

    llm_response = [
        {
            "name": "Refund request",
            "description": "### Background\nCaller wants refund.\n### Caller Intent\nGet money back.",
            "goal": "Obtain refund confirmation",
        }
    ]
    import json

    monkeypatch.setattr(
        llm_service_module.llm_service,
        "generate_response",
        lambda **_kwargs: {"text": json.dumps(llm_response)},
    )

    response = authenticated_client.post(
        "/api/v1/agents/generate-scenarios-from-prompt",
        json={
            "test_agent_prompt": "## Purpose\nSupport refunds.",
            "agent_name": "Support Bot",
            "scenario_count": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["scenarios"]) == 1
    assert body["scenarios"][0]["name"] == "Refund request"
    assert body["scenarios"][0]["goal"] == "Obtain refund confirmation"


def test_generate_test_setup_runs_both_stages(authenticated_client, monkeypatch, make_ai_provider):
    from importlib import import_module

    llm_service_module = import_module("app.services.ai.llm_service")
    make_ai_provider(provider="openai")

    prompt_text = (
        "## Role\nYou are a patient calling to book an appointment.\n\n"
        "Behave naturally and provide details when asked."
    )
    scenario_json = [
        {
            "name": "Book appointment",
            "description": "### Background\nNew patient.\n### Caller Intent\nSchedule visit.",
            "goal": "Book slot",
        }
    ]
    import json

    call_count = {"n": 0}

    def fake_generate(**_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"text": prompt_text}
        return {"text": json.dumps(scenario_json)}

    monkeypatch.setattr(llm_service_module.llm_service, "generate_response", fake_generate)

    response = authenticated_client.post(
        "/api/v1/agents/generate-test-setup",
        json={
            "production_prompt": "You book medical appointments.",
            "agent_name": "Scheduler",
            "scenario_count": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sections"] == []
    assert "book an appointment" in body["test_agent_prompt"]
    assert len(body["scenarios"]) == 1
    assert call_count["n"] == 2


def test_generate_test_prompt_requires_production_prompt(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/agents/generate-test-prompt",
        json={"production_prompt": "   ", "agent_name": "Bot"},
    )
    assert response.status_code == 422 or response.status_code == 400
