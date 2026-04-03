"""API tests for conversation-evaluations routes."""


def test_create_conversation_evaluation(authenticated_client, monkeypatch, make_manual_transcription, make_agent):
    from app.api.v1.routes import conversation_evaluations as conv_routes

    transcription = make_manual_transcription()
    agent = make_agent()

    monkeypatch.setattr(conv_routes.s3_service, "is_enabled", lambda: False)
    monkeypatch.setattr(
        conv_routes.llm_service,
        "generate_response",
        lambda **_kwargs: {
            "text": (
                '{"objective_achieved": true, "objective_achieved_reason": "Resolved", '
                '"additional_metrics": {"overall_quality": 0.9}, "overall_score": 0.9}'
            ),
            "model": "gpt-4o-mini",
            "usage": {"total_tokens": 50},
            "processing_time": 0.2,
        },
    )

    payload = {
        "transcription_id": str(transcription.id),
        "agent_id": str(agent.id),
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
    }
    response = authenticated_client.post("/api/v1/conversation-evaluations", json=payload)

    assert response.status_code == 201
    assert response.json()["objective_achieved"] is True
    assert response.json()["overall_score"] == 0.9


def test_list_get_delete_conversation_evaluation(
    authenticated_client, make_manual_transcription, make_agent, make_conversation_evaluation
):
    transcription = make_manual_transcription()
    agent = make_agent()
    evaluation = make_conversation_evaluation(transcription_id=transcription.id, agent_id=agent.id)

    list_response = authenticated_client.get("/api/v1/conversation-evaluations")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/conversation-evaluations/{evaluation.id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == str(evaluation.id)

    delete_response = authenticated_client.delete(f"/api/v1/conversation-evaluations/{evaluation.id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Evaluation deleted successfully"
