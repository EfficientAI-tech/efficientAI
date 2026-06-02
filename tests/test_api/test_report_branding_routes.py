from types import SimpleNamespace
from importlib import import_module

from app.models.database import Workspace


def _fake_s3():
    store: dict[str, tuple[bytes, str]] = {}

    def upload_file_by_key(content: bytes, key: str, content_type: str):
        store[key] = (content, content_type)
        return key

    def download_file_by_key(key: str) -> bytes:
        return store[key][0]

    def delete_file_by_key(key: str) -> bool:
        store.pop(key, None)
        return True

    return SimpleNamespace(
        store=store,
        prefix="test-prefix/",
        is_enabled=lambda: True,
        get_status_message=lambda: None,
        upload_file_by_key=upload_file_by_key,
        download_file_by_key=download_file_by_key,
        delete_file_by_key=delete_file_by_key,
    )


def test_report_branding_images_heading_upload_and_retrieve(
    authenticated_client, db_session, org_id, seed_org, monkeypatch
):
    s3_module = import_module("app.services.storage.s3_service")

    fake_s3 = _fake_s3()
    monkeypatch.setattr(s3_module, "s3_service", fake_s3)

    empty = authenticated_client.get("/api/v1/settings/report-branding")
    assert empty.status_code == 200
    assert empty.json()["has_logo"] is False
    assert empty.json()["heading"] is None
    assert empty.json()["images"] == []

    heading = authenticated_client.patch(
        "/api/v1/settings/report-branding",
        json={"heading": "Acme QA Report"},
    )
    assert heading.status_code == 200
    assert heading.json()["heading"] == "Acme QA Report"

    response = authenticated_client.post(
        "/api/v1/settings/report-branding/images",
        files=[
            ("files", ("logo.png", b"png-bytes", "image/png")),
            ("files", ("brand.webp", b"webp-bytes", "image/webp")),
        ],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_logo"] is True
    assert body["heading"] == "Acme QA Report"
    assert [image["filename"] for image in body["images"]] == [
        "logo.png",
        "brand.webp",
    ]
    assert body["images"][0]["data_uri"].startswith("data:image/png;base64,")

    workspace = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .one()
    )
    assert workspace.report_branding["images"][0]["s3_key"].startswith(
        f"test-prefix/organizations/{org_id}/workspaces/{workspace.id}/report_branding/"
    )
    image_id = body["images"][0]["id"]

    retrieved = authenticated_client.get("/api/v1/settings/report-branding")
    assert retrieved.status_code == 200
    assert retrieved.json()["images"][0]["data_uri"] == body["images"][0]["data_uri"]

    deleted = authenticated_client.delete(f"/api/v1/settings/report-branding/images/{image_id}")
    assert deleted.status_code == 200
    assert [image["filename"] for image in deleted.json()["images"]] == ["brand.webp"]


def test_report_branding_rejects_unsupported_logo(
    authenticated_client, monkeypatch
):
    s3_module = import_module("app.services.storage.s3_service")

    monkeypatch.setattr(s3_module, "s3_service", _fake_s3())
    response = authenticated_client.post(
        "/api/v1/settings/report-branding/images",
        files={"files": ("logo.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 400
    assert "png" in response.json()["detail"].lower()
