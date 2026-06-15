"""API tests for manual-evaluations routes."""

from uuid import uuid4


def _org_key(org_id, filename: str = "audio.wav", prefix: str = "audio/") -> str:
    return f"{prefix}organizations/{org_id}/audio/{filename}"


def test_list_audio_files_and_presigned_url(authenticated_client, monkeypatch, org_id):
    from app.api.v1.routes import manual_evaluations as manual_routes
    from app.config import settings

    own_key = _org_key(org_id)
    monkeypatch.setattr(settings, "S3_PREFIX", "audio", raising=False)
    monkeypatch.setattr(manual_routes.s3_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        manual_routes.s3_service,
        "get_organization_root_prefix",
        lambda organization_id: f"audio/organizations/{organization_id}/",
    )
    monkeypatch.setattr(
        manual_routes.s3_service,
        "list_audio_files",
        lambda **_kwargs: [
            {
                "key": own_key,
                "filename": "audio.wav",
                "size": 1234,
                "last_modified": "2026-01-01T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        manual_routes.s3_service,
        "generate_presigned_url_by_key",
        lambda key, expiration=3600: f"https://example.com/{key}?exp={expiration}",
    )

    list_response = authenticated_client.get("/api/v1/manual-evaluations/audio-files")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    encoded_key = own_key.replace("/", "%2F")
    url_response = authenticated_client.get(
        f"/api/v1/manual-evaluations/audio-files/{encoded_key}/presigned-url"
    )
    assert url_response.status_code == 200
    assert f"https://example.com/{own_key}" in url_response.json()["url"]


def test_manual_evaluations_presigned_url_rejects_cross_tenant_key(
    authenticated_client, monkeypatch, org_id
):
    from app.api.v1.routes import manual_evaluations as manual_routes
    from app.config import settings

    monkeypatch.setattr(settings, "S3_PREFIX", "audio", raising=False)
    monkeypatch.setattr(manual_routes.s3_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        manual_routes.s3_service,
        "get_organization_root_prefix",
        lambda organization_id: f"audio/organizations/{organization_id}/",
    )

    victim_key = _org_key(uuid4())
    encoded_key = victim_key.replace("/", "%2F")
    response = authenticated_client.get(
        f"/api/v1/manual-evaluations/audio-files/{encoded_key}/presigned-url"
    )
    assert response.status_code == 403


def test_transcribe_audio_creates_transcription(authenticated_client, monkeypatch):
    from app.api.v1.routes import manual_evaluations as manual_routes

    monkeypatch.setattr(manual_routes.s3_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        manual_routes.transcription_service,
        "transcribe",
        lambda **_kwargs: {
            "transcript": "hello from audio",
            "speaker_segments": [{"speaker": "agent", "text": "hello"}],
            "language": "en",
            "processing_time": 0.31,
            "raw_output": {"provider": "openai"},
        },
    )

    payload = {
        "audio_file_key": "organizations/test/audio.wav",
        "stt_provider": "openai",
        "stt_model": "whisper-1",
        "name": "Call #1",
    }
    response = authenticated_client.post("/api/v1/manual-evaluations/transcribe", json=payload)

    assert response.status_code == 201
    assert response.json()["transcript"] == "hello from audio"
    assert response.json()["name"] == "Call #1"


def test_get_update_delete_transcription(authenticated_client, make_manual_transcription):
    transcription = make_manual_transcription(name="Initial Name")

    get_response = authenticated_client.get(f"/api/v1/manual-evaluations/transcriptions/{transcription.id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Initial Name"

    patch_response = authenticated_client.patch(
        f"/api/v1/manual-evaluations/transcriptions/{transcription.id}",
        json={"name": "Renamed Transcription"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["name"] == "Renamed Transcription"

    delete_response = authenticated_client.delete(
        f"/api/v1/manual-evaluations/transcriptions/{transcription.id}"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Transcription deleted successfully"
