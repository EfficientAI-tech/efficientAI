"""API tests for evaluation routes."""

from app.models.enums import EvaluationStatus


class _FakeTaskResult:
    id = "task-1"


def test_create_evaluation_success(authenticated_client, monkeypatch, make_audio):
    from app.api.v1.routes import evaluations as evaluations_route

    audio = make_audio()
    monkeypatch.setattr(
        evaluations_route.process_evaluation_task,
        "delay",
        lambda *_args, **_kwargs: _FakeTaskResult(),
    )

    payload = {
        "audio_id": str(audio.id),
        "evaluation_type": "asr",
        "metrics": ["wer", "latency"],
    }
    response = authenticated_client.post("/api/v1/evaluations/create", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["audio_id"] == str(audio.id)
    assert body["status"] == EvaluationStatus.PENDING.value


def test_create_evaluation_missing_audio_returns_404(authenticated_client):
    payload = {
        "audio_id": "11111111-1111-1111-1111-111111111111",
        "evaluation_type": "asr",
        "metrics": ["wer"],
    }
    response = authenticated_client.post("/api/v1/evaluations/create", json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == "Audio file not found"


def test_get_and_list_evaluations(authenticated_client, make_evaluation):
    evaluation = make_evaluation()

    get_response = authenticated_client.get(f"/api/v1/evaluations/{evaluation.id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == str(evaluation.id)

    list_response = authenticated_client.get("/api/v1/evaluations")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_cancel_evaluation_changes_status(authenticated_client, db_session, make_evaluation):
    evaluation = make_evaluation(status=EvaluationStatus.PENDING.value)

    response = authenticated_client.post(f"/api/v1/evaluations/{evaluation.id}/cancel")
    assert response.status_code == 200
    assert response.json()["message"] == "Evaluation cancelled successfully"

    db_session.refresh(evaluation)
    assert evaluation.status == EvaluationStatus.CANCELLED.value


def test_delete_evaluation_success(authenticated_client, db_session, make_evaluation):
    evaluation = make_evaluation()

    response = authenticated_client.delete(f"/api/v1/evaluations/{evaluation.id}")

    assert response.status_code == 200
    assert response.json()["message"] == "Evaluation deleted successfully"
    assert db_session.get(type(evaluation), evaluation.id) is None
