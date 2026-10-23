"""Migration middleware reuses an up-to-date result and rechecks while pending."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.migration_middleware import MigrationCheckMiddleware
from app.core.migrations import clear_migration_status_cache


def _api_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(MigrationCheckMiddleware)

    @app.get("/api/v1/ping")
    def ping():
        return {"ok": True}

    return TestClient(app)


def test_middleware_checks_migrations_once_when_current(monkeypatch):
    clear_migration_status_cache()
    calls = {"n": 0}

    def _check():
        calls["n"] += 1
        return (True, [])

    monkeypatch.setattr("app.core.migrations.check_migrations_status", _check)
    client = _api_client()

    assert client.get("/api/v1/ping").status_code == 200
    assert client.get("/api/v1/ping").status_code == 200
    assert calls["n"] == 1
    clear_migration_status_cache()


def test_middleware_rechecks_while_migrations_are_pending(monkeypatch):
    clear_migration_status_cache()
    calls = {"n": 0}

    def _check():
        calls["n"] += 1
        return (False, ["099_pending"])

    monkeypatch.setattr("app.core.migrations.check_migrations_status", _check)
    client = _api_client()

    first = client.get("/api/v1/ping")
    second = client.get("/api/v1/ping")

    assert first.status_code == 503
    assert second.status_code == 503
    assert calls["n"] == 2
    clear_migration_status_cache()
