"""Tests for Vobiz telephony edge routing (webhooks on media, not API)."""

from starlette.routing import WebSocketRoute

from app.api.v1.media import media_router
from app.api.v1.routes import vobiz_telephony
from app.config import apply_service_mode, settings


def _collect_route_paths(routes, prefix: str = ""):
    for route in routes:
        path = getattr(route, "path", "") or ""
        full = f"{prefix}{path}".replace("//", "/")
        yield full
        if hasattr(route, "routes"):
            yield from _collect_route_paths(route.routes, full)


def _router_paths(router) -> set[str]:
    return set(_collect_route_paths(router.routes))


def test_crud_router_excludes_carrier_webhooks():
    paths = _router_paths(vobiz_telephony.router)
    assert not any("/webhooks/" in p for p in paths)


def test_webhook_router_exposes_carrier_callbacks():
    paths = _router_paths(vobiz_telephony.webhook_router)
    assert any(p.endswith("/webhooks/answer") for p in paths)
    assert any(p.endswith("/webhooks/events") for p in paths)
    assert any(p.endswith("/webhooks/recording-ready") for p in paths)


def test_ws_router_exposes_vobiz_media_socket():
    paths = _router_paths(vobiz_telephony.ws_router)
    assert any(p.endswith("/ws") for p in paths)
    for route in vobiz_telephony.ws_router.routes:
        assert isinstance(route, WebSocketRoute)


def test_media_router_mounts_vobiz_edge_routers():
    paths = _router_paths(media_router)
    assert any("/telephony/vobiz/webhooks/answer" in p for p in paths)
    assert any("/telephony/vobiz/ws" in p for p in paths)


def test_split_api_mode_skips_media_routes(monkeypatch):
    monkeypatch.setenv("SERVICE_MODE", "api")
    apply_service_mode("api")
    monkeypatch.setattr(settings, "MEDIA_WS_BASE_URL", "ws://localhost:8001")

    from app.app_factory import _includes_media_routes

    assert _includes_media_routes() is False


def test_media_service_mode_includes_media_routes(monkeypatch):
    monkeypatch.setenv("SERVICE_MODE", "media")
    apply_service_mode("media")
    monkeypatch.setattr(settings, "MEDIA_WS_BASE_URL", "")

    from app.app_factory import _includes_media_routes

    assert _includes_media_routes() is True
