"""Tests for operational endpoint access controls."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import settings
from app.core.health import build_health_status
from app.core.migration_middleware import MigrationCheckMiddleware
from app.core.operational_access_middleware import (
    OperationalAccessMiddleware,
    is_operational_access_allowed,
)


def _request(
    *,
    client_host: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    path: str = "/health",
) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "client": (client_host, 12345),
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


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


def test_spoofed_user_agent_does_not_bypass_gate(monkeypatch):
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", False)
    monkeypatch.setattr(settings, "OPERATIONAL_TRUSTED_IPS", ["10.0.0.0/8"])

    request = _request(
        client_host="203.0.113.1",
        headers=[(b"user-agent", b"ELB-HealthChecker/2.0")],
    )

    assert is_operational_access_allowed(request) is False


def test_direct_trusted_peer_without_xff_allowed(monkeypatch):
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", False)
    monkeypatch.setattr(settings, "OPERATIONAL_TRUSTED_IPS", ["10.0.0.0/8"])

    request = _request(client_host="10.1.2.3")

    assert is_operational_access_allowed(request) is True


def test_health_allowed_for_trusted_client_ip_via_proxy(monkeypatch):
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", False)
    monkeypatch.setattr(settings, "OPERATIONAL_TRUSTED_IPS", ["10.0.0.0/8"])

    request = _request(
        client_host="10.0.0.50",
        headers=[(b"x-forwarded-for", b"10.1.2.3")],
    )

    assert is_operational_access_allowed(request) is True


def test_public_client_via_trusted_proxy_is_blocked(monkeypatch):
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", False)
    monkeypatch.setattr(settings, "OPERATIONAL_TRUSTED_IPS", ["10.0.0.0/8"])

    request = _request(
        client_host="10.0.0.50",
        headers=[(b"x-forwarded-for", b"203.0.113.1")],
    )

    assert is_operational_access_allowed(request) is False


def test_spoofed_leftmost_xff_without_trusted_peer_is_blocked(monkeypatch):
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", False)
    monkeypatch.setattr(settings, "OPERATIONAL_TRUSTED_IPS", ["10.0.0.0/8"])

    request = _request(
        client_host="203.0.113.1",
        headers=[(b"x-forwarded-for", b"10.0.0.1")],
    )

    assert is_operational_access_allowed(request) is False


def test_metrics_blocked_for_public_client(operational_client):
    response = operational_client.get(
        "/metrics",
        headers={"X-Forwarded-For": "203.0.113.1"},
    )

    assert response.status_code == 404


def test_metrics_allowed_for_trusted_client_ip(operational_client, monkeypatch):
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", False)
    monkeypatch.setattr(settings, "OPERATIONAL_TRUSTED_IPS", ["10.0.0.0/8"])

    request = _request(
        client_host="10.0.0.50",
        path="/metrics",
        headers=[(b"x-forwarded-for", b"10.1.2.3")],
    )

    assert is_operational_access_allowed(request) is True


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
