import httpx
import pytest

from efficientai.integrations.efficientai_traces.pipecat_upstream import (
    ensure_trace_session,
    setup_pipecat_worker_tracing,
    trace_session_enabled,
)


@pytest.mark.asyncio
async def test_ensure_trace_session_soft_fail_on_connect(monkeypatch):
    monkeypatch.setenv("EFFICIENTAI_API_KEY", "key")
    monkeypatch.setenv("EFFICIENTAI_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv("EFFICIENTAI_API_BASE", "http://127.0.0.1:9")

    ctx = await ensure_trace_session(transport="webrtc", strict=False)
    assert ctx["enabled"] is False
    assert ctx.get("error")
    assert "Cannot connect" in ctx["error"] or "connect" in ctx["error"].lower()


@pytest.mark.asyncio
async def test_ensure_trace_session_strict_raises(monkeypatch):
    monkeypatch.setenv("EFFICIENTAI_API_KEY", "key")
    monkeypatch.setenv("EFFICIENTAI_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv("EFFICIENTAI_API_BASE", "http://127.0.0.1:9")

    with pytest.raises(Exception):
        await ensure_trace_session(transport="webrtc", strict=True)


def test_setup_pipecat_worker_tracing_noop_when_disabled():
    tracing = setup_pipecat_worker_tracing({"enabled": False, "error": "nope"})
    assert tracing["enabled"] is False
    assert tracing["additional_span_attributes"] == {}
    assert trace_session_enabled({"enabled": False}) is False
