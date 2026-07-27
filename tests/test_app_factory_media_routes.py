"""Tests for API/media route co-location in app factory."""

import os

from app import app_factory
from app.config import settings


def test_api_colocates_media_when_no_separate_media_url(monkeypatch):
    monkeypatch.setattr(settings, "SERVICE_MODE", "api")
    monkeypatch.setattr(settings, "MEDIA_WS_BASE_URL", "")
    assert app_factory._includes_media_routes() is True


def test_api_skips_media_when_separate_media_url_configured(monkeypatch):
    monkeypatch.setattr(settings, "SERVICE_MODE", "api")
    monkeypatch.setattr(settings, "MEDIA_WS_BASE_URL", "ws://localhost:8001")
    assert app_factory._includes_media_routes() is False


def test_media_app_mounts_ws_after_stale_api_service_mode(monkeypatch):
    """Media subprocess spawned by start-all can inherit SERVICE_MODE=api."""
    monkeypatch.setenv("SERVICE_MODE", "api")
    monkeypatch.setenv("MEDIA_WS_BASE_URL", "ws://localhost:8001")

    from app.config import apply_service_mode, settings

    settings.SERVICE_MODE = "api"
    settings.MEDIA_WS_BASE_URL = "ws://localhost:8001"
    assert app_factory._includes_media_routes() is False

    apply_service_mode("media")
    assert settings.SERVICE_MODE == "media"
    assert app_factory._includes_media_routes() is True


def test_apply_service_mode_updates_settings_and_env(monkeypatch):
    from app.config import apply_service_mode, settings

    monkeypatch.delenv("SERVICE_MODE", raising=False)
    apply_service_mode("media")
    assert settings.SERVICE_MODE == "media"
    assert os.environ["SERVICE_MODE"] == "media"


def test_service_mode_reads_from_env_over_stale_settings(monkeypatch):
    monkeypatch.setenv("SERVICE_MODE", "media")
    monkeypatch.setattr(settings, "SERVICE_MODE", "api")
    assert app_factory._service_mode() == "media"
    assert app_factory._includes_media_routes() is True
