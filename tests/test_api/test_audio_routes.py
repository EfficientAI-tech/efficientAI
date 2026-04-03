"""API tests for audio routes."""


def test_list_audio_files(authenticated_client, make_audio):
    make_audio(filename="one.wav")
    make_audio(filename="two.wav")

    response = authenticated_client.get("/api/v1/audio")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_audio_file(authenticated_client, make_audio):
    audio = make_audio(filename="meta.wav")

    response = authenticated_client.get(f"/api/v1/audio/{audio.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(audio.id)
    assert response.json()["filename"] == "meta.wav"


def test_delete_audio_file(authenticated_client, monkeypatch, make_audio):
    from app.api.v1.routes import audio as audio_route

    audio = make_audio(filename="remove.wav", format="wav")
    monkeypatch.setattr(audio_route.storage_service, "delete_file", lambda *_args, **_kwargs: True)

    response = authenticated_client.delete(f"/api/v1/audio/{audio.id}")

    assert response.status_code == 200
    assert response.json()["message"] == "Audio file deleted successfully"


def test_get_audio_with_invalid_uuid_returns_400(authenticated_client):
    response = authenticated_client.get("/api/v1/audio/not-a-uuid")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid audio ID format"
