"""Tests for selective Host header validation."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.core.trusted_host_middleware import SelectiveTrustedHostMiddleware


@pytest.fixture
def host_client(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_HOSTS", ["sandbox.efficientai.cloud"])
    monkeypatch.setattr(settings, "OPERATIONAL_TRUSTED_IPS", ["10.0.0.0/8"])

    app = FastAPI()
    app.add_middleware(SelectiveTrustedHostMiddleware, allowed_hosts=settings.TRUSTED_HOSTS)

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    @app.get("/api/v1/ping")
    def ping():
        return {"ok": True}

    with TestClient(app) as client:
        yield client


def test_health_allows_internal_ip_host_header(host_client):
    response = host_client.get("/health", headers={"Host": "10.20.2.137"})

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_health_allows_public_domain_host_header(host_client):
    response = host_client.get("/health", headers={"Host": "sandbox.efficientai.cloud"})

    assert response.status_code == 200


def test_api_allows_configured_public_host(host_client):
    response = host_client.get("/api/v1/ping", headers={"Host": "sandbox.efficientai.cloud"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_api_allows_host_ip_in_operational_trusted_ips(host_client):
    response = host_client.get("/api/v1/ping", headers={"Host": "10.20.2.137"})

    assert response.status_code == 200


def test_api_rejects_untrusted_host(host_client):
    response = host_client.get("/api/v1/ping", headers={"Host": "evil.example.com"})

    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_api_rejects_missing_host_header(host_client):
    response = host_client.get("/api/v1/ping", headers={"Host": ""})

    assert response.status_code == 400
