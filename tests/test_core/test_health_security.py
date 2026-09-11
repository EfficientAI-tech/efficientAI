"""Tests for /health abuse protection and information disclosure boundaries."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.config import settings
from app.core.api_rate_limit import check_health_rate_limit
from app.core.health import build_liveness_status, build_readiness_status
from app.core.migration_middleware import MigrationCheckMiddleware
from app.core.operational_access_middleware import OperationalAccessMiddleware


@pytest.fixture
def health_app(monkeypatch):
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", False)
    monkeypatch.setattr(settings, "OPERATIONAL_TRUSTED_IPS", ["10.0.0.0/8"])
    monkeypatch.setattr(settings, "API_RATE_LIMIT_ENFORCE", True)
    monkeypatch.setattr(settings, "HEALTH_RATE_LIMIT_PER_MINUTE", 3)
    monkeypatch.setattr(settings, "HEALTH_READINESS_CACHE_SECONDS", 0)

    def _is_trusted_probe(request: Request) -> bool:
        return request.headers.get("x-test-trusted-probe") == "1"

    monkeypatch.setattr(
        "app.core.operational_access_middleware.is_operational_access_allowed",
        _is_trusted_probe,
    )

    app = FastAPI()
    app.add_middleware(MigrationCheckMiddleware)
    app.add_middleware(OperationalAccessMiddleware)

    @app.get("/health")
    def health(request: Request):
        from app.core.operational_access_middleware import is_operational_access_allowed

        check_health_rate_limit(request)
        if is_operational_access_allowed(request):
            payload, status_code = build_readiness_status(detailed=False)
        else:
            payload, status_code = build_liveness_status()
        return JSONResponse(content=payload, status_code=status_code)

    with TestClient(app) as client:
        yield client


def test_public_health_is_liveness_only_when_migrations_pending(monkeypatch, health_app):
    monkeypatch.setattr(
        "app.core.health.check_migrations_status",
        lambda: (False, ["099_pending.sql"]),
    )

    response = health_app.get("/health", headers={"X-Forwarded-For": "203.0.113.1"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_trusted_lb_peer_gets_readiness_when_migrations_pending(monkeypatch, health_app):
    monkeypatch.setattr(
        "app.core.health.check_migrations_status",
        lambda: (False, ["099_pending.sql"]),
    )

    response = health_app.get("/health", headers={"x-test-trusted-probe": "1"})

    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}


def test_public_health_rate_limited(monkeypatch, health_app):
    monkeypatch.setattr(
        "app.core.health.check_migrations_status",
        lambda: (True, []),
    )

    headers = {"X-Forwarded-For": "198.51.100.9"}
    counts = iter([1, 2, 3, 4])
    with patch("app.core.api_rate_limit._sliding_window_count", side_effect=lambda *a, **k: next(counts)):
        for _ in range(3):
            assert health_app.get("/health", headers=headers).status_code == 200

        blocked = health_app.get("/health", headers=headers)
        assert blocked.status_code == 429


def test_trusted_lb_peer_not_rate_limited(monkeypatch, health_app):
    monkeypatch.setattr(
        "app.core.health.check_migrations_status",
        lambda: (True, []),
    )

    headers = {"x-test-trusted-probe": "1"}
    for _ in range(6):
        assert health_app.get("/health", headers=headers).status_code == 200
