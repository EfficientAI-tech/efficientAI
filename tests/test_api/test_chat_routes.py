"""API tests for chat routes."""


def test_chat_completion(authenticated_client, monkeypatch):
    from app.api.v1.routes import chat as chat_routes

    monkeypatch.setattr(
        chat_routes.llm_service,
        "generate_response",
        lambda **_kwargs: {
            "text": "hello from assistant",
            "model": "gpt-4o-mini",
            "usage": {"total_tokens": 12},
            "processing_time": 0.11,
        },
    )

    payload = {
        "messages": [{"role": "user", "content": "Say hello"}],
        "provider": "openai",
        "model": "gpt-4o-mini",
        "temperature": 0.2,
    }
    response = authenticated_client.post("/api/v1/chat/completion", json=payload)

    assert response.status_code == 200
    assert response.json()["text"] == "hello from assistant"
