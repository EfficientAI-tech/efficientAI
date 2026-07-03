"""Tests for operational endpoint access control."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.core.operational_access_middleware import (
    OperationalAccessMiddleware,
    is_operational_path,
)


@pytest.fixture
def operational_client(monkeypatch):
    monkeypatch.setattr(settings, "OPERATIONAL_PUBLIC", False)
    monkeypatch.setattr(settings, "OPERATIONAL_TRUSTED_IPS", [])

    app = FastAPI()
    app.add_middleware(OperationalAccessMiddleware)

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    @app.get("/metrics")
    def metrics():
        return {"ok": True}

    with TestClient(app) as client:
        yield client


def test_health_allowed_without_trusted_ips(operational_client):
    response = operational_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_metrics_blocked_without_trusted_ips(operational_client):
    response = operational_client.get("/metrics")
    assert response.status_code == 404


def test_is_operational_path_matches_prometheus_only():
    assert is_operational_path("/metrics") is True
    assert is_operational_path("/metrics/") is True
    assert is_operational_path("/metrics-management") is False
    assert is_operational_path("/health") is False
