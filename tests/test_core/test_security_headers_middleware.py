"""Tests for HTTP security response headers."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app.config import settings
from app.core.security_headers_middleware import SecurityHeadersMiddleware


@pytest.fixture
def security_client(tmp_path):
    """Minimal app with SecurityHeadersMiddleware (avoids heavy conftest client)."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    @app.get("/api/v1/auth/config")
    def auth_config():
        return {"providers": []}

    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (assets_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    with TestClient(app) as client:
        yield client


def test_health_includes_baseline_security_headers(security_client):
    response = security_client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"


def test_api_routes_include_private_no_store_cache(security_client):
    response = security_client.get("/api/v1/auth/config")

    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert "private" in response.headers["Cache-Control"]


def test_csp_report_only_header_when_enabled(security_client, monkeypatch):
    monkeypatch.setattr(settings, "CSP_ENABLED", True)
    monkeypatch.setattr(settings, "CSP_REPORT_ONLY", True)

    response = security_client.get("/health")

    assert "Content-Security-Policy-Report-Only" in response.headers
    assert "Content-Security-Policy" not in response.headers
    assert "default-src 'self'" in response.headers["Content-Security-Policy-Report-Only"]


def test_csp_enforcing_header_when_report_only_disabled(security_client, monkeypatch):
    monkeypatch.setattr(settings, "CSP_ENABLED", True)
    monkeypatch.setattr(settings, "CSP_REPORT_ONLY", False)

    response = security_client.get("/health")

    assert "Content-Security-Policy" in response.headers
    assert "Content-Security-Policy-Report-Only" not in response.headers


def test_csp_allows_voice_provider_connect_src(security_client, monkeypatch):
    monkeypatch.setattr(settings, "CSP_ENABLED", True)
    monkeypatch.setattr(settings, "CSP_REPORT_ONLY", False)

    response = security_client.get("/health")
    policy = response.headers["Content-Security-Policy"]

    assert "https://api.vapi.ai" in policy
    assert "https://*.daily.co" in policy
    assert "wss://*.livekit.cloud" in policy
    assert "https://api.elevenlabs.io" in policy
    assert "https://*.ingest.sentry.io" in policy
    assert "'unsafe-eval'" in policy
    assert "blob:" in policy
    assert "https://c.daily.co" in policy
    assert "worker-src 'self' blob:" in policy


def test_csp_allows_frame_src_for_pdf_preview_and_voice(security_client, monkeypatch):
    monkeypatch.setattr(settings, "CSP_ENABLED", True)
    monkeypatch.setattr(settings, "CSP_REPORT_ONLY", False)

    response = security_client.get("/health")
    policy = response.headers["Content-Security-Policy"]

    assert "frame-src 'self' blob:" in policy
    assert "https://*.daily.co" in policy
    assert "https://*.s3.amazonaws.com" in policy
    assert "https://*.amazonaws.com" in policy
    assert "https://*.cloudfront.net" in policy
    assert "https://storage.googleapis.com" in policy
    assert "https://*.blob.core.windows.net" in policy


def test_csp_skipped_for_openapi_docs_paths(security_client, monkeypatch):
    monkeypatch.setattr(settings, "CSP_ENABLED", True)
    monkeypatch.setattr(settings, "CSP_REPORT_ONLY", False)

    @security_client.app.get("/docs")
    def swagger_docs():
        return {"ok": True}

    @security_client.app.get("/docs/oauth2-redirect")
    def swagger_oauth():
        return {"ok": True}

    @security_client.app.get("/redoc")
    def redoc():
        return {"ok": True}

    @security_client.app.get("/openapi.json")
    def openapi():
        return {"openapi": "3.1.0"}

    for path in ("/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"):
        response = security_client.get(path)
        assert response.status_code == 200
        assert "Content-Security-Policy" not in response.headers
        assert "Content-Security-Policy-Report-Only" not in response.headers


def test_asset_routes_use_long_cache(security_client):
    response = security_client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert "Pragma" not in response.headers


@pytest.mark.skipif(
    not (Path(settings.FRONTEND_DIR) / "assets").is_dir(),
    reason="frontend dist assets not built in test environment",
)
def test_built_frontend_assets_use_long_cache():
    """Integration check when frontend/dist exists locally."""
    assets_dir = Path(settings.FRONTEND_DIR) / "assets"
    asset_file = next(assets_dir.iterdir())

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    with TestClient(app) as client:
        response = client.get(f"/assets/{asset_file.name}")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
