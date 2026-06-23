"""Tests for operational endpoint access controls."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.config import settings
from app.core.health import build_health_status
from app.core.migration_middleware import MigrationCheckMiddleware
from app.core.operational_access_middleware import OperationalAccessMiddleware


@pytest.fixture
def operational_client(monkeypatch):
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", False)
    monkeypatch.setattr(settings, "OPERATIONAL_TRUSTED_IPS", ["10.0.0.0/8"])
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(
        "app.core.health.check_migrations_status",
        lambda: (True, []),
    )

    app = FastAPI()
    app.add_middleware(MigrationCheckMiddleware)
    app.add_middleware(OperationalAccessMiddleware)

    @app.get("/health")
    def health():
        payload, status_code = build_health_status(detailed=False)
        return JSONResponse(content=payload, status_code=status_code)

    @app.get("/metrics")
    def metrics():
        return "metrics"

    with TestClient(app) as client:
        yield client


def test_public_health_via_alb_is_blocked(operational_client):
    response = operational_client.get(
        "/health",
        headers={"X-Forwarded-For": "203.0.113.1", "User-Agent": "SecurityScanner/1.0"},
    )

    assert response.status_code == 404


def test_alb_health_probe_is_allowed(operational_client):
    response = operational_client.get(
        "/health",
        headers={"User-Agent": "ELB-HealthChecker/2.0"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_health_allowed_for_trusted_client_ip(operational_client):
    response = operational_client.get(
        "/health",
        headers={"X-Forwarded-For": "10.1.2.3", "User-Agent": "Mozilla/5.0"},
    )

    assert response.status_code == 200
    assert set(response.json().keys()) == {"status"}


def test_metrics_blocked_for_public_client(operational_client):
    response = operational_client.get(
        "/metrics",
        headers={"X-Forwarded-For": "203.0.113.1"},
    )

    assert response.status_code == 404


def test_metrics_allowed_for_trusted_client_ip(operational_client):
    response = operational_client.get(
        "/metrics",
        headers={"X-Forwarded-For": "10.1.2.3"},
    )

    assert response.status_code == 200
    assert response.json() == "metrics"


def test_operational_public_allows_anonymous_health(monkeypatch):
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", True)
    monkeypatch.setattr(settings, "OPERATIONAL_TRUSTED_IPS", [])

    app = FastAPI()
    app.add_middleware(OperationalAccessMiddleware)

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    with TestClient(app) as client:
        response = client.get(
            "/health",
            headers={"X-Forwarded-For": "203.0.113.1"},
        )

    assert response.status_code == 200


def test_docs_not_registered_when_debug_disabled(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "app.api.v1.api",
        SimpleNamespace(api_router=APIRouter()),
    )
    monkeypatch.setattr(settings, "FRONTEND_DIR", "__missing_frontend__")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    from app.main import create_app

    monkeypatch.setattr(settings, "DEBUG", False)
    app = create_app()
    route_paths = {getattr(route, "path", None) for route in app.routes}

    assert "/docs" not in route_paths
    assert "/redoc" not in route_paths
    assert "/openapi.json" not in route_paths


def test_build_health_status_minimal_excludes_migration_details(monkeypatch):
    monkeypatch.setattr(
        "app.core.health.check_migrations_status",
        lambda: (False, ["033_add_workspaces.sql"]),
    )

    payload, status_code = build_health_status(detailed=False)

    assert status_code == 503
    assert payload == {"status": "degraded"}
    assert "pending_migrations" not in payload


def test_build_health_status_detailed_includes_migration_details(monkeypatch):
    monkeypatch.setattr(
        "app.core.health.check_migrations_status",
        lambda: (False, ["033_add_workspaces.sql"]),
    )

    payload, status_code = build_health_status(detailed=True)

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["pending_migrations"] == ["033_add_workspaces.sql"]


def test_health_detail_returns_migration_info_for_admin(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "app.api.v1.api",
        SimpleNamespace(api_router=APIRouter()),
    )
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", True)
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "FRONTEND_DIR", "__missing_frontend__")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)
    monkeypatch.setattr(
        "app.core.health.check_migrations_status",
        lambda: (True, []),
    )

    from app.core.auth.rbac import require_admin
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: object()

    with TestClient(app) as client:
        response = client.get("/health/detail")

    assert response.status_code == 200
    assert response.json()["migrations"] == "up_to_date"


def test_health_detail_requires_authentication_via_create_app(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "app.api.v1.api",
        SimpleNamespace(api_router=APIRouter()),
    )
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", True)
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "FRONTEND_DIR", "__missing_frontend__")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    from app.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/health/detail")

    assert response.status_code == 401
