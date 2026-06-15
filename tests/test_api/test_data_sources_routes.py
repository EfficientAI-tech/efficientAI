"""API tests for S3 data-source routes."""

from uuid import uuid4

import pytest


def _org_key(org_id, filename: str = "audio.wav", prefix: str = "audio/") -> str:
    return f"{prefix}organizations/{org_id}/audio/{filename}"


def _patch_storage(
    monkeypatch, data_routes, org_id, *, prefix: str = "audio/", blob_provider: str = "s3"
):
    from app.config import settings

    if blob_provider == "gcs":
        monkeypatch.setattr(settings, "GCS_PREFIX", prefix.rstrip("/"), raising=False)
    else:
        monkeypatch.setattr(settings, "S3_PREFIX", prefix.rstrip("/"), raising=False)

    monkeypatch.setattr(data_routes.s3_service, "is_enabled", lambda: True)
    monkeypatch.setattr(data_routes.s3_service, "get_status_message", lambda: "ok")
    monkeypatch.setattr(
        data_routes.s3_service,
        "get_organization_root_prefix",
        lambda organization_id: f"{prefix}organizations/{organization_id}/",
    )
    monkeypatch.setattr(
        data_routes.s3_service,
        "list_audio_files",
        lambda **_kwargs: [
            {
                "key": _org_key(org_id, prefix=prefix),
                "filename": "audio.wav",
                "size": 42,
                "last_modified": "2026-01-01T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        data_routes.s3_service,
        "download_file_by_key",
        lambda key: b"audio-bytes" if key.startswith(f"{prefix}organizations/") else b"",
    )
    monkeypatch.setattr(
        data_routes.s3_service,
        "generate_presigned_url_by_key",
        lambda key, expiration=3600: f"https://example.com/{key}?exp={expiration}",
    )
    monkeypatch.setattr(data_routes.s3_service, "delete_file_by_key", lambda _key: None)


@pytest.mark.parametrize("blob_provider,prefix", [("s3", "audio/"), ("gcs", "gcs-audio/")])
def test_s3_status_list_presigned_and_delete(
    authenticated_client, monkeypatch, org_id, blob_provider, prefix
):
    from app.api.v1.routes import data_sources as data_routes
    from app.config import settings

    monkeypatch.setattr(settings, "BLOB_STORAGE_PROVIDER", blob_provider)
    _patch_storage(
        monkeypatch, data_routes, org_id, prefix=prefix, blob_provider=blob_provider
    )
    own_key = _org_key(org_id, prefix=prefix)
    encoded_key = own_key.replace("/", "%2F")

    status_response = authenticated_client.get("/api/v1/data-sources/s3/status")
    assert status_response.status_code == 200
    assert status_response.json()["enabled"] is True

    list_response = authenticated_client.get("/api/v1/data-sources/s3/files")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    presigned_response = authenticated_client.get(
        f"/api/v1/data-sources/s3/files/{encoded_key}/presigned-url"
    )
    assert presigned_response.status_code == 200
    assert f"https://example.com/{own_key}" in presigned_response.json()["url"]

    delete_response = authenticated_client.delete(f"/api/v1/data-sources/s3/files/{own_key}")
    assert delete_response.status_code == 200


@pytest.mark.parametrize("blob_provider,prefix", [("s3", "audio/"), ("gcs", "gcs-audio/")])
def test_blob_routes_reject_cross_tenant_keys(
    authenticated_client, monkeypatch, org_id, blob_provider, prefix
):
    from app.api.v1.routes import data_sources as data_routes
    from app.config import settings

    monkeypatch.setattr(settings, "BLOB_STORAGE_PROVIDER", blob_provider)
    _patch_storage(
        monkeypatch, data_routes, org_id, prefix=prefix, blob_provider=blob_provider
    )

    victim_org_id = uuid4()
    victim_key = _org_key(victim_org_id, prefix=prefix)
    encoded_victim_key = victim_key.replace("/", "%2F")

    download_response = authenticated_client.get(
        f"/api/v1/data-sources/s3/files/{victim_key}/download"
    )
    assert download_response.status_code == 403

    presigned_response = authenticated_client.get(
        f"/api/v1/data-sources/s3/files/{encoded_victim_key}/presigned-url"
    )
    assert presigned_response.status_code == 403

    delete_response = authenticated_client.delete(
        f"/api/v1/data-sources/s3/files/{victim_key}"
    )
    assert delete_response.status_code == 403


@pytest.mark.parametrize("blob_provider,prefix", [("s3", "audio/"), ("gcs", "gcs-audio/")])
def test_blob_download_allows_own_org_key(
    authenticated_client, monkeypatch, org_id, blob_provider, prefix
):
    from app.api.v1.routes import data_sources as data_routes
    from app.config import settings

    monkeypatch.setattr(settings, "BLOB_STORAGE_PROVIDER", blob_provider)
    _patch_storage(
        monkeypatch, data_routes, org_id, prefix=prefix, blob_provider=blob_provider
    )
    own_key = _org_key(org_id, prefix=prefix)

    response = authenticated_client.get(
        f"/api/v1/data-sources/s3/files/{own_key}/download"
    )
    assert response.status_code == 200
