import sys
from types import SimpleNamespace

from fastapi import APIRouter

from app.config import settings


def _route_paths(app):
    return {getattr(route, "path", None) for route in app.routes}


def _stub_api_router(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "app.api.v1.api",
        SimpleNamespace(api_router=APIRouter()),
    )


def test_metrics_route_is_not_registered_when_observability_is_disabled(monkeypatch):
    _stub_api_router(monkeypatch)
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)
    monkeypatch.setattr(settings, "FRONTEND_DIR", "__missing_frontend__")

    from app.main import create_app

    app = create_app()

    assert "/metrics" not in _route_paths(app)


def test_metrics_route_is_registered_when_observability_is_enabled(monkeypatch):
    _stub_api_router(monkeypatch)

    class FakeInstrumentator:
        def __init__(self, **_kwargs):
            pass

        def instrument(self, app):
            return self

        def expose(self, app, endpoint="/metrics", include_in_schema=False):
            @app.get(endpoint, include_in_schema=include_in_schema)
            async def metrics():
                return "ok"

            return self

    monkeypatch.setitem(
        sys.modules,
        "prometheus_fastapi_instrumentator",
        SimpleNamespace(Instrumentator=FakeInstrumentator),
    )
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "FRONTEND_DIR", "__missing_frontend__")

    from app.main import create_app

    app = create_app()

    assert "/metrics" in _route_paths(app)
