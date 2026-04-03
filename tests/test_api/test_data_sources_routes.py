"""API tests for S3 data-source routes."""


def test_s3_status_list_presigned_and_delete(authenticated_client, monkeypatch):
    from app.api.v1.routes import data_sources as data_routes

    monkeypatch.setattr(data_routes.s3_service, "is_enabled", lambda: True)
    monkeypatch.setattr(data_routes.s3_service, "get_status_message", lambda: "ok")
    monkeypatch.setattr(
        data_routes.s3_service,
        "list_audio_files",
        lambda **_kwargs: [
            {
                "key": "org/audio.wav",
                "filename": "audio.wav",
                "size": 42,
                "last_modified": "2026-01-01T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        data_routes.s3_service,
        "generate_presigned_url_by_key",
        lambda key, expiration=3600: f"https://example.com/{key}?exp={expiration}",
    )
    monkeypatch.setattr(data_routes.s3_service, "delete_file_by_key", lambda _key: None)

    status_response = authenticated_client.get("/api/v1/data-sources/s3/status")
    assert status_response.status_code == 200
    assert status_response.json()["enabled"] is True

    list_response = authenticated_client.get("/api/v1/data-sources/s3/files")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    presigned_response = authenticated_client.get(
        "/api/v1/data-sources/s3/files/org%2Faudio.wav/presigned-url"
    )
    assert presigned_response.status_code == 200
    assert "https://example.com/org/audio.wav" in presigned_response.json()["url"]

    delete_response = authenticated_client.delete("/api/v1/data-sources/s3/files/org/audio.wav")
    assert delete_response.status_code == 200
