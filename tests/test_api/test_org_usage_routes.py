"""Ensure org usage API routes are mounted on the v1 router."""

from datetime import date
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.api import api_router
from app.api.v1.routes import usage_pricing
from app.database import get_db
from app.dependencies import get_organization_id


def test_org_usage_routes_are_registered():
    paths = {route.path for route in api_router.routes if hasattr(route, "path")}
    assert "/organizations/usage/summary" in paths
    assert "/organizations/usage/breakdown" in paths
    assert "/organizations/usage/filters" in paths
    assert "/organizations/usage/fx-rate" in paths
    assert "/organizations/usage/pricing/overrides" in paths
    assert "/organizations/usage/pricing/overrides/{model:path}" in paths


def _override_client(monkeypatch, seen: list[str]) -> TestClient:
    def fake_get_effective_rate(db, *, organization_id, model, usage_kind, as_of):
        del db, organization_id
        seen.append(model)
        return {
            "model": model,
            "usage_kind": usage_kind,
            "as_of": as_of,
            "catalog_rates": {"input_per_1m": 1.5, "output_per_1m": 9.0},
            "catalog_rate_id": None,
            "override": None,
            "effective_rates": {"input_per_1m": 1.5, "output_per_1m": 9.0},
            "effective_source": "catalog",
            "effective_rate_id": None,
            "has_override": False,
        }

    monkeypatch.setattr(usage_pricing, "get_effective_rate", fake_get_effective_rate)
    app = FastAPI()
    app.include_router(usage_pricing.router)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_organization_id] = lambda: uuid4()
    for dep in usage_pricing.router.dependencies:
        app.dependency_overrides[dep.dependency] = lambda: None
    return TestClient(app)


def test_pricing_override_get_accepts_encoded_slash_model_id(monkeypatch):
    seen: list[str] = []
    client = _override_client(monkeypatch, seen)

    response = client.get(
        "/organizations/usage/pricing/overrides/google%2Fgemini-3.5-flash",
        params={"usage_kind": "llm", "as_of": "2026-11-10"},
    )

    assert response.status_code == 200
    assert seen == ["google/gemini-3.5-flash"]
    body = response.json()
    assert body["model"] == "google/gemini-3.5-flash"
    assert body["as_of"] == date(2026, 11, 10).isoformat()
    assert body["effective_rates"]["input_per_1m"] == 1.5


def test_pricing_override_get_still_accepts_plain_model_id(monkeypatch):
    seen: list[str] = []
    client = _override_client(monkeypatch, seen)

    response = client.get(
        "/organizations/usage/pricing/overrides/gpt-4o",
        params={"usage_kind": "llm"},
    )

    assert response.status_code == 200
    assert seen == ["gpt-4o"]
    assert response.json()["model"] == "gpt-4o"
