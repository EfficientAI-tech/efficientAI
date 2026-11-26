"""Trace sessions: open a session per call, export spans against it, close it at hang-up.

Typical flow for any agent stack::

    trace_ctx = await ensure_trace_session(transport="websocket", handshake=first_message)
    setup_worker_tracing(trace_ctx)          # point OTLP export at this call
    ...                                      # run the call; spans are exported
    await close_trace_session(trace_ctx)     # flush spans and close the session

Every function here degrades gracefully: unless ``strict=True``, failures are logged and
the agent keeps running without traces.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from efficientai_sdk._client import AsyncEfficientAI
from efficientai_sdk._config import ENV_API_KEY, ENV_WORKSPACE_ID, resolve_config
from efficientai_sdk._exceptions import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    ConfigurationError,
    EfficientAIError,
)
from efficientai_sdk.tracing.correlation import span_correlation_attributes
from efficientai_sdk.tracing.handshake import parse_trace_handshake
from efficientai_sdk.tracing.otel import flush_efficientai_tracing, setup_efficientai_tracing

logger = logging.getLogger("efficientai_sdk.tracing")

__all__ = [
    "DEFAULT_OTLP_PATH",
    "SESSIONS_PATH",
    "VALID_TRANSPORTS",
    "TraceSessionError",
    "close_trace_session",
    "ensure_trace_session",
    "mint_trace_session",
    "missing_deployment_trace_env",
    "require_deployment_trace_env",
    "resolve_otlp_endpoint",
    "resolve_trace_transport",
    "setup_worker_tracing",
    "trace_session_enabled",
    "warn_deployment_trace_env",
]

DEFAULT_OTLP_PATH = "/api/v1/observability/traces"
SESSIONS_PATH = "/api/v1/observability/traces/sessions"
VALID_TRANSPORTS = frozenset({"webrtc", "websocket", "phone", "custom"})
_SESSION_TIMEOUT = 20.0


class TraceSessionError(EfficientAIError):
    """The session API failed (connection, HTTP status, or bad response)."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _api_base_url(explicit: Optional[str] = None) -> str:
    # Any non-empty key works here: only the base URL is used.
    return resolve_config(api_key="unused", base_url=explicit).base_url


def resolve_otlp_endpoint(
    server_hint: Optional[str] = None, *, api_base_url: Optional[str] = None
) -> str:
    """OTLP ingest URL to export to.

    ``EFFICIENTAI_OTLP_ENDPOINT`` wins. Otherwise the server's hint is used, unless it
    would downgrade an https deployment to http (common behind TLS-terminating proxies).
    """
    explicit = _env("EFFICIENTAI_OTLP_ENDPOINT")
    if explicit:
        return explicit.rstrip("/")
    base = _api_base_url(api_base_url)
    canonical = f"{base}{DEFAULT_OTLP_PATH}"
    if not server_hint or not str(server_hint).strip():
        return canonical
    hint = str(server_hint).strip().rstrip("/")
    if base.startswith("https://") and hint.startswith("http://"):
        return canonical
    return hint


def missing_deployment_trace_env() -> list[str]:
    """Environment variables still needed when no handshake is present."""
    return [name for name in (ENV_API_KEY, ENV_WORKSPACE_ID) if not _env(name)]


def require_deployment_trace_env() -> None:
    """Raise ``ConfigurationError`` if the trace environment is incomplete."""
    missing = missing_deployment_trace_env()
    if missing:
        raise ConfigurationError(
            "Missing EfficientAI trace environment variables: "
            + ", ".join(missing)
            + ". Set them in the agent's environment and restart it."
        )


def warn_deployment_trace_env() -> list[str]:
    """Log missing variables and return them. The agent can still run without traces."""
    missing = missing_deployment_trace_env()
    if missing:
        logger.warning(
            "EfficientAI call traces disabled: missing %s. The agent will run without "
            "exporting spans.",
            ", ".join(missing),
        )
    return missing


def resolve_trace_transport(runner_args: Any = None, transport: Any = None) -> str:
    """Infer the call transport (webrtc, websocket, phone, custom) for session labelling."""
    explicit = (_env("EFFICIENTAI_TRACE_TRANSPORT") or "").lower()
    if explicit in VALID_TRANSPORTS:
        return explicit

    if runner_args is not None:
        runner_transport = getattr(runner_args, "transport", None)
        if isinstance(runner_transport, str) and runner_transport.lower() in VALID_TRANSPORTS:
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


def _run_id_from(otel: dict[str, Any], fallback: Any = None) -> Optional[str]:
    """Simulation result id carried in the server's ``otel_correlation`` block."""
    attrs = otel.get("suggested_span_attributes") or {}
    value = attrs.get("efficientai.evaluator_result_id") or fallback
    return str(value) if value else None


def _disabled_trace_context(error: str) -> dict[str, Any]:
    return {"enabled": False, "error": error, "call_short_id": None}


def trace_session_enabled(trace_ctx: dict[str, Any]) -> bool:
    return bool(trace_ctx.get("enabled") and trace_ctx.get("call_short_id"))


async def mint_trace_session(
    *,
    workspace_id: str,
    api_key: str,
    api_base_url: Optional[str] = None,
    transport: str = "websocket",
    evaluator_result_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> dict[str, Any]:
    """Open a trace session. The server mints the six-digit ``call_short_id``.

    Raises ``TraceSessionError`` on any failure.
    """
    payload: dict[str, Any] = {"transport": transport}
    if evaluator_result_id:
        payload["evaluator_result_id"] = str(evaluator_result_id)
    if agent_id:
        payload["agent_id"] = str(agent_id)

    try:
        client = AsyncEfficientAI(
            api_key=api_key,
            workspace_id=workspace_id,
            base_url=api_base_url,
            timeout=_SESSION_TIMEOUT,
        )
    except ConfigurationError as exc:
        raise TraceSessionError(str(exc)) from exc
    url = f"{client.base_url}{SESSIONS_PATH}"
    try:
        body = await client.request("POST", SESSIONS_PATH, json=payload)
    except APIStatusError as exc:
        raise TraceSessionError(
            f"Session API error {exc} (POST {url})", status_code=exc.status_code
        ) from exc
    except APITimeoutError as exc:
        raise TraceSessionError(f"Timed out calling EfficientAI session API at {url}") from exc
    except APIConnectionError as exc:
        raise TraceSessionError(
            f"Cannot connect to EfficientAI at {url} (check EFFICIENTAI_BASE_URL and the "
            f"network). Detail: {exc}"
        ) from exc
    finally:
        await client.close()

    if not isinstance(body, dict) or not body.get("call_short_id"):
        raise TraceSessionError(f"Unexpected response from {url}: {body!r}")
    return body


async def ensure_trace_session(
    *,
    transport: str = "websocket",
    handshake: Optional[dict[str, Any]] = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Resolve the trace context for this call.

    Sources, in order:

    1. An EfficientAI handshake message (test calls from the platform).
    2. ``EFFICIENTAI_CALL_SHORT_ID`` (manual development fallback).
    3. A new session from the session API, using ``EFFICIENTAI_API_KEY`` and
       ``EFFICIENTAI_WORKSPACE_ID``.

    Unless ``strict`` is set, failures return ``{"enabled": False, "error": ...}`` so the
    agent can carry on without traces.
    """
    if handshake:
        parsed = parse_trace_handshake(handshake)
        if parsed:
            otel = parsed.get("otel_correlation") or {}
            return {
                "enabled": True,
                "call_short_id": parsed["call_short_id"],
                "agent_id": parsed.get("agent_id"),
                "workspace_id": parsed.get("workspace_id"),
                "transport": parsed.get("transport") or transport,
                "evaluator_result_id": _run_id_from(otel, handshake.get("evaluator_result_id")),
                "otlp_endpoint": resolve_otlp_endpoint(otel.get("otlp_endpoint")),
            }

    call_short_id = _env("EFFICIENTAI_CALL_SHORT_ID")
    if call_short_id:
        return {
            "enabled": True,
            "call_short_id": call_short_id,
            "agent_id": _env("EFFICIENTAI_AGENT_ID"),
            "workspace_id": _env(ENV_WORKSPACE_ID),
            "transport": transport,
            "otlp_endpoint": resolve_otlp_endpoint(),
        }

    missing = missing_deployment_trace_env()
    if missing:
        if strict:
            require_deployment_trace_env()
        msg = "Missing EfficientAI env: " + ", ".join(missing)
        logger.warning("%s. The agent will run without call traces.", msg)
        return _disabled_trace_context(msg)

    api_key = _env(ENV_API_KEY) or ""
    workspace_id = _env(ENV_WORKSPACE_ID) or ""
    try:
        session = await mint_trace_session(
            workspace_id=workspace_id,
            api_key=api_key,
            transport=transport,
            agent_id=_env("EFFICIENTAI_AGENT_ID"),
        )
    except TraceSessionError as exc:
        if strict:
            raise
        logger.error("EfficientAI trace session failed: %s", exc)
        return _disabled_trace_context(str(exc))

    otel = session.get("otel_correlation") or {}
    return {
        "enabled": True,
        "call_short_id": session["call_short_id"],
        "trace_id": session.get("trace_id"),
        "workspace_id": session.get("workspace_id") or workspace_id,
        "transport": session.get("transport") or transport,
        "evaluator_result_id": _run_id_from(otel),
        "otlp_endpoint": resolve_otlp_endpoint(otel.get("otlp_endpoint")),
    }


def setup_worker_tracing(
    trace_ctx: dict[str, Any], *, service_name: str = "pipecat-agent"
) -> dict[str, Any]:
    """Point OTLP export at the call in ``trace_ctx``.

    Returns ``enabled`` plus ``additional_span_attributes`` to pass to a pipeline (for
    example Pipecat's ``PipelineTask``). A disabled context is a no-op.
    """
    if not trace_session_enabled(trace_ctx):
        return {
            "enabled": False,
            "additional_span_attributes": {},
            "call_short_id": None,
            "transport": trace_ctx.get("transport"),
        }

    call_short_id = trace_ctx["call_short_id"]
    agent_id = trace_ctx.get("agent_id")
    workspace_id = trace_ctx.get("workspace_id")
    transport = trace_ctx.get("transport")
    run_id = trace_ctx.get("evaluator_result_id")

    setup_efficientai_tracing(
        service_name=service_name,
        call_short_id=call_short_id,
        evaluator_result_id=str(run_id) if run_id else None,
        agent_id=str(agent_id) if agent_id else None,
        workspace_id=str(workspace_id) if workspace_id else None,
        transport=str(transport) if transport else None,
        otlp_endpoint=trace_ctx.get("otlp_endpoint"),
        api_key=_env(ENV_API_KEY),
    )

    attrs = span_correlation_attributes(
        call_short_id=call_short_id,
        evaluator_result_id=str(run_id) if run_id else None,
        agent_id=str(agent_id) if agent_id else None,
        workspace_id=str(workspace_id) if workspace_id else None,
        transport=str(transport) if transport else None,
    )
    return {
        "enabled": True,
        "additional_span_attributes": attrs,
        "call_short_id": call_short_id,
        "transport": transport,
    }


async def close_trace_session(trace_ctx: dict[str, Any]) -> None:
    """Flush spans and close the session. Never raises; failures are logged."""
    if not trace_session_enabled(trace_ctx):
        return
    flush_efficientai_tracing()

    call_short_id = trace_ctx.get("call_short_id")
    api_key = _env(ENV_API_KEY)
    workspace_id = trace_ctx.get("workspace_id") or _env(ENV_WORKSPACE_ID)
    if not call_short_id or not api_key or not workspace_id:
        return

    try:
        client = AsyncEfficientAI(
            api_key=api_key, workspace_id=str(workspace_id), timeout=_SESSION_TIMEOUT
        )
    except EfficientAIError as exc:
        logger.warning("EfficientAI trace close skipped: %s", exc)
        return
    try:
        await client.request("POST", f"{SESSIONS_PATH}/{call_short_id}/close")
    except EfficientAIError as exc:
        logger.warning("EfficientAI trace close failed: %s", exc)
    finally:
        await client.close()
