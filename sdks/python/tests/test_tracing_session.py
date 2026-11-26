from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from efficientai_sdk import ConfigurationError
from efficientai_sdk.tracing import (
    TraceSessionError,
    close_trace_session,
    ensure_trace_session,
    mint_trace_session,
    resolve_otlp_endpoint,
    resolve_trace_transport,
    setup_worker_tracing,
    trace_session_enabled,
)
from efficientai_sdk.tracing import session as session_mod

BASE = "http://agent-host.test"
SESSIONS = f"{BASE}/api/v1/observability/traces/sessions"


@pytest.fixture
def trace_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EFFICIENTAI_API_KEY", "key")
    monkeypatch.setenv("EFFICIENTAI_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv("EFFICIENTAI_BASE_URL", BASE)


def session_body(**extra: Any) -> dict[str, Any]:
    body = {
        "trace_id": "t-1",
        "call_short_id": "482931",
        "workspace_id": "ws-1",
        "transport": "websocket",
        "status": "open",
        "otel_correlation": {"otlp_endpoint": f"{BASE}/api/v1/observability/traces"},
    }
    body.update(extra)
    return body


# ---- mint ---------------------------------------------------------------


@respx.mock
async def test_mint_sends_auth_and_payload() -> None:
    route = respx.post(SESSIONS).respond(200, json=session_body())
    body = await mint_trace_session(
        workspace_id="ws-1",
        api_key="key",
        api_base_url=BASE,
        transport="webrtc",
        evaluator_result_id="run-9",
        agent_id="agent-1",
    )
    assert body["call_short_id"] == "482931"
    req = route.calls.last.request
    assert req.headers["X-API-Key"] == "key"
    assert req.headers["X-Workspace-Id"] == "ws-1"
    assert json.loads(req.content) == {
        "transport": "webrtc",
        "evaluator_result_id": "run-9",
        "agent_id": "agent-1",
    }


@respx.mock
async def test_mint_http_error_becomes_trace_session_error() -> None:
    respx.post(SESSIONS).respond(401, json={"detail": "Invalid API key"})
    with pytest.raises(TraceSessionError) as info:
        await mint_trace_session(workspace_id="ws-1", api_key="bad", api_base_url=BASE)
    assert info.value.status_code == 401
    assert "Invalid API key" in str(info.value)


@respx.mock
async def test_mint_rejects_response_without_call_id() -> None:
    respx.post(SESSIONS).respond(200, json={"trace_id": "t"})
    with pytest.raises(TraceSessionError, match="Unexpected response"):
        await mint_trace_session(workspace_id="ws-1", api_key="key", api_base_url=BASE)


# ---- ensure (ported framework behaviour) --------------------------------


async def test_ensure_soft_fails_on_connect(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    monkeypatch.setenv("EFFICIENTAI_API_KEY", "key")
    monkeypatch.setenv("EFFICIENTAI_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv("EFFICIENTAI_API_BASE", "http://127.0.0.1:9")  # legacy name
    ctx = await ensure_trace_session(transport="webrtc", strict=False)
    assert ctx["enabled"] is False
    assert "Cannot connect" in ctx["error"]


async def test_ensure_strict_raises_on_connect(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    monkeypatch.setenv("EFFICIENTAI_API_KEY", "key")
    monkeypatch.setenv("EFFICIENTAI_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv("EFFICIENTAI_API_BASE", "http://127.0.0.1:9")
    with pytest.raises(TraceSessionError):
        await ensure_trace_session(transport="webrtc", strict=True)


async def test_ensure_missing_env_disables_or_raises() -> None:
    ctx = await ensure_trace_session()
    assert ctx["enabled"] is False
    assert "EFFICIENTAI_API_KEY" in ctx["error"]
    with pytest.raises(ConfigurationError):
        await ensure_trace_session(strict=True)
    with pytest.raises(ValueError):  # backwards compatible with the old helpers
        await ensure_trace_session(strict=True)


@respx.mock
async def test_ensure_mints_session(trace_env: None) -> None:
    respx.post(SESSIONS).respond(
        200,
        json=session_body(
            otel_correlation={
                "otlp_endpoint": f"{BASE}/api/v1/observability/traces",
                "suggested_span_attributes": {"efficientai.evaluator_result_id": "run-1"},
            }
        ),
    )
    ctx = await ensure_trace_session(transport="websocket")
    assert trace_session_enabled(ctx)
    assert ctx["call_short_id"] == "482931"
    assert ctx["evaluator_result_id"] == "run-1"
    assert ctx["otlp_endpoint"] == f"{BASE}/api/v1/observability/traces"


async def test_ensure_prefers_handshake(trace_env: None) -> None:
    ctx = await ensure_trace_session(
        handshake={
            "type": "efficientai_trace_handshake",
            "call_short_id": "123456",
            "agent_id": "a1",
            "workspace_id": "w1",
            "transport": "webrtc",
            "otel_correlation": {
                "otlp_endpoint": f"{BASE}/api/v1/observability/traces",
                "suggested_span_attributes": {"efficientai.evaluator_result_id": "run-7"},
            },
        }
    )
    assert ctx["call_short_id"] == "123456"
    assert ctx["agent_id"] == "a1"
    assert ctx["transport"] == "webrtc"
    assert ctx["evaluator_result_id"] == "run-7"


async def test_ensure_uses_env_call_id(trace_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EFFICIENTAI_CALL_SHORT_ID", "654321")
    ctx = await ensure_trace_session()
    assert ctx["call_short_id"] == "654321"
    assert ctx["workspace_id"] == "ws-1"


# ---- otlp endpoint + transport ------------------------------------------


def test_otlp_endpoint_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EFFICIENTAI_OTLP_ENDPOINT", "https://collector.test/v1/traces/")
    assert resolve_otlp_endpoint("http://other") == "https://collector.test/v1/traces"


def test_otlp_endpoint_defaults_to_localhost() -> None:
    assert resolve_otlp_endpoint() == "http://localhost:8000/api/v1/observability/traces"


def test_otlp_endpoint_refuses_https_to_http_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EFFICIENTAI_BASE_URL", "https://eai.example")
    assert (
        resolve_otlp_endpoint("http://internal:8000/api/v1/observability/traces")
        == "https://eai.example/api/v1/observability/traces"
    )


def test_resolve_trace_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    class Args:
        transport = "Phone"

    class FastAPIWebsocketTransport:
        pass

    assert resolve_trace_transport(Args()) == "phone"
    assert resolve_trace_transport(transport=FastAPIWebsocketTransport()) == "websocket"
    assert resolve_trace_transport() == "webrtc"
    monkeypatch.setenv("EFFICIENTAI_TRACE_TRANSPORT", "custom")
    assert resolve_trace_transport(Args()) == "custom"


# ---- worker setup + close -----------------------------------------------


def test_setup_worker_tracing_noop_when_disabled() -> None:
    tracing = setup_worker_tracing({"enabled": False, "error": "nope"})
    assert tracing["enabled"] is False
    assert tracing["additional_span_attributes"] == {}
    assert trace_session_enabled({"enabled": False}) is False


def test_setup_worker_tracing_returns_correlation_attrs(
    trace_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(session_mod, "setup_efficientai_tracing", lambda **kw: calls.append(kw))
    tracing = setup_worker_tracing(
        {
            "enabled": True,
            "call_short_id": "482931",
            "workspace_id": "ws-1",
            "transport": "webrtc",
            "evaluator_result_id": "run-1",
            "otlp_endpoint": "http://x/api/v1/observability/traces",
        }
    )
    attrs = tracing["additional_span_attributes"]
    assert attrs["efficientai.call_short_id"] == "482931"
    assert attrs["efficientai.evaluator_result_id"] == "run-1"
    assert calls[0]["evaluator_result_id"] == "run-1"
    assert calls[0]["api_key"] == "key"


@respx.mock
async def test_close_posts_close(trace_env: None) -> None:
    route = respx.post(f"{SESSIONS}/482931/close").respond(200, json={})
    await close_trace_session({"enabled": True, "call_short_id": "482931", "workspace_id": "ws-1"})
    assert route.called


@respx.mock
async def test_close_never_raises(trace_env: None, sleeps: list[float]) -> None:
    respx.post(f"{SESSIONS}/482931/close").mock(side_effect=httpx.ConnectError("down"))
    await close_trace_session({"enabled": True, "call_short_id": "482931"})


async def test_close_skips_disabled_context() -> None:
    await close_trace_session({"enabled": False})
