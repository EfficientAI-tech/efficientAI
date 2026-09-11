"""Bridge upstream pipecat-ai (PipelineWorker) to EfficientAI trace ingest."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from efficientai.integrations.efficientai_traces.correlation import span_correlation_attributes
from efficientai.integrations.efficientai_traces.handshake import parse_trace_handshake
from efficientai.integrations.efficientai_traces.setup import setup_efficientai_tracing, flush_efficientai_tracing

DEFAULT_API_BASE = os.environ.get("EFFICIENTAI_API_BASE", "http://localhost:8000").rstrip("/")
DEFAULT_OTLP_PATH = "/api/v1/observability/traces"
_VALID_TRANSPORTS = frozenset({"webrtc", "websocket", "phone", "custom"})


def _env(name: str) -> Optional[str]:
    val = os.environ.get(name)
    return str(val).strip() if val and str(val).strip() else None


def missing_deployment_trace_env() -> list[str]:
    """Return unset deployment env vars needed when no handshake is present."""
    required = (
        "EFFICIENTAI_API_KEY",
        "EFFICIENTAI_WORKSPACE_ID",
    )
    return [name for name in required if not _env(name)]


def require_deployment_trace_env() -> None:
    """Fail fast with a clear message before accepting a WebRTC/WebSocket call."""
    missing = missing_deployment_trace_env()
    if missing:
        raise ValueError(
            "Missing EfficientAI trace env in pipecat .env: "
            + ", ".join(missing)
            + ". Add them once (see docs/synthetic-call-traces-pipecat.md), then restart bot.py."
        )


def resolve_trace_transport(runner_args: Any = None, transport: Any = None) -> str:
    """Infer the active Pipecat transport for trace session labeling."""
    explicit = (_env("EFFICIENTAI_TRACE_TRANSPORT") or "").lower()
    if explicit in _VALID_TRANSPORTS:
        return explicit

    if runner_args is not None:
        runner_transport = getattr(runner_args, "transport", None)
        if isinstance(runner_transport, str) and runner_transport.lower() in _VALID_TRANSPORTS:
            return runner_transport.lower()
        if getattr(runner_args, "websocket", None) is not None:
            return "websocket"

    if transport is not None:
        type_name = type(transport).__name__.lower()
        module_name = (type(transport).__module__ or "").lower()
        if "webrtc" in type_name or "webrtc" in module_name:
            return "webrtc"
        if "websocket" in type_name or "websocket" in module_name:
            return "websocket"

    return "webrtc"


async def mint_trace_session(
    *,
    workspace_id: str,
    api_key: str,
    api_base_url: str = DEFAULT_API_BASE,
    transport: str = "websocket",
    evaluator_result_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Open an EfficientAI trace session (call_short_id minted server-side)."""
    payload: Dict[str, Any] = {"transport": transport}
    if evaluator_result_id:
        payload["evaluator_result_id"] = evaluator_result_id

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{api_base_url}/api/v1/observability/traces/sessions",
            headers={
                "X-API-Key": api_key,
                "X-Workspace-Id": workspace_id,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def ensure_trace_session(
    *,
    transport: str = "websocket",
    handshake: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Resolve per-call trace context.

    Priority:
    1. EfficientAI WS handshake (playground custom WebSocket)
    2. EFFICIENTAI_CALL_SHORT_ID env (manual dev fallback)
    3. POST /observability/traces/sessions using deployment env (API key + workspace)
    """
    if handshake:
        parsed = parse_trace_handshake(handshake)
        if parsed:
            otel = parsed.get("otel_correlation") or {}
            return {
                "call_short_id": parsed["call_short_id"],
                "agent_id": parsed.get("agent_id"),
                "workspace_id": parsed.get("workspace_id"),
                "otlp_endpoint": otel.get("otlp_endpoint")
                or f"{DEFAULT_API_BASE}{DEFAULT_OTLP_PATH}",
            }

    call_short_id = _env("EFFICIENTAI_CALL_SHORT_ID")
    if call_short_id:
        return {
            "call_short_id": call_short_id,
            "agent_id": _env("EFFICIENTAI_AGENT_ID"),
            "workspace_id": _env("EFFICIENTAI_WORKSPACE_ID"),
            "otlp_endpoint": _env("EFFICIENTAI_OTLP_ENDPOINT")
            or f"{DEFAULT_API_BASE}{DEFAULT_OTLP_PATH}",
        }

    api_key = _env("EFFICIENTAI_API_KEY")
    workspace_id = _env("EFFICIENTAI_WORKSPACE_ID")
    if not api_key or not workspace_id:
        require_deployment_trace_env()

    session = await mint_trace_session(
        workspace_id=workspace_id,
        api_key=api_key,
        transport=transport,
    )
    otel = session.get("otel_correlation") or {}
    return {
        "call_short_id": session["call_short_id"],
        "trace_id": session.get("trace_id"),
        "workspace_id": session.get("workspace_id") or workspace_id,
        "transport": session.get("transport") or transport,
        "otlp_endpoint": otel.get("otlp_endpoint") or f"{DEFAULT_API_BASE}{DEFAULT_OTLP_PATH}",
    }


def setup_pipecat_worker_tracing(trace_ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Configure OTLP export and return kwargs for upstream ``PipelineWorker``.

    Usage::

        trace_ctx = await ensure_trace_session()
        tracing = setup_pipecat_worker_tracing(trace_ctx)
        worker = PipelineWorker(
            pipeline,
            enable_tracing=True,
            additional_span_attributes=tracing["additional_span_attributes"],
            ...
        )
    """
    call_short_id = trace_ctx["call_short_id"]
    agent_id = trace_ctx.get("agent_id")
    workspace_id = trace_ctx.get("workspace_id")
    transport = trace_ctx.get("transport")
    otlp_endpoint = trace_ctx.get("otlp_endpoint")

    setup_efficientai_tracing(
        service_name="pipecat-agent",
        call_short_id=call_short_id,
        agent_id=str(agent_id) if agent_id else None,
        workspace_id=str(workspace_id) if workspace_id else None,
        transport=str(transport) if transport else None,
        otlp_endpoint=otlp_endpoint,
        api_key=_env("EFFICIENTAI_API_KEY"),
    )

    attrs = span_correlation_attributes(
        call_short_id=call_short_id,
        agent_id=str(agent_id) if agent_id else None,
        workspace_id=str(workspace_id) if workspace_id else None,
        transport=str(transport) if transport else None,
    )
    return {
        "additional_span_attributes": attrs,
        "call_short_id": call_short_id,
        "transport": transport,
    }


async def close_trace_session(trace_ctx: Dict[str, Any]) -> None:
    """Close trace row when Pipecat call ends."""
    flush_efficientai_tracing()
    call_short_id = trace_ctx.get("call_short_id")
    api_key = _env("EFFICIENTAI_API_KEY")
    workspace_id = trace_ctx.get("workspace_id") or _env("EFFICIENTAI_WORKSPACE_ID")
    if not call_short_id or not api_key or not workspace_id:
        return
    async with httpx.AsyncClient(timeout=20.0) as client:
        await client.post(
            f"{DEFAULT_API_BASE}/api/v1/observability/traces/sessions/{call_short_id}/close",
            headers={"X-API-Key": api_key, "X-Workspace-Id": str(workspace_id)},
        )
