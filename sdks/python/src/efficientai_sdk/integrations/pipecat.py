"""Pipecat helpers. These return keyword arguments for ``PipelineTask`` and don't import
Pipecat themselves, so they work with any Pipecat version that supports
``enable_tracing`` and ``additional_span_attributes``.

Example::

    task = PipelineTask(
        pipeline,
        **configure_pipecat_tracing(sip_headers=inbound_headers),
    )
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Optional

from efficientai_sdk.tracing.correlation import span_correlation_attributes
from efficientai_sdk.tracing.handshake import parse_trace_handshake
from efficientai_sdk.tracing.otel import _resolve_call_short_id, setup_efficientai_tracing
from efficientai_sdk.tracing.session import setup_worker_tracing

__all__ = [
    "configure_pipecat_tracing",
    "configure_pipecat_tracing_from_handshake",
    "setup_pipecat_worker_tracing",
]


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def configure_pipecat_tracing(
    *,
    call_short_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    otlp_endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    sip_headers: Optional[Mapping[str, Any]] = None,
    webhook_params: Optional[Mapping[str, Any]] = None,
    handshake: Optional[Mapping[str, Any]] = None,
    additional_span_attributes: Optional[dict[str, str]] = None,
    service_name: str = "pipecat-agent",
) -> dict[str, Any]:
    """Configure OTLP export for this call and return ``PipelineTask`` keyword arguments."""
    if handshake is not None:
        return configure_pipecat_tracing_from_handshake(
            handshake, api_key=api_key, service_name=service_name
        )

    setup_efficientai_tracing(
        service_name=service_name,
        call_short_id=call_short_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
        otlp_endpoint=otlp_endpoint,
        api_key=api_key,
        sip_headers=sip_headers,
        webhook_params=webhook_params,
    )
    attrs = span_correlation_attributes(
        call_short_id=_resolve_call_short_id(
            call_short_id=call_short_id, sip_headers=sip_headers, webhook_params=webhook_params
        ),
        evaluator_result_id=_env("EFFICIENTAI_RUN_ID"),
        agent_id=agent_id or _env("EFFICIENTAI_AGENT_ID"),
        workspace_id=workspace_id or _env("EFFICIENTAI_WORKSPACE_ID"),
    )
    if additional_span_attributes:
        attrs.update(additional_span_attributes)
    return {"enable_tracing": True, "additional_span_attributes": attrs}


def configure_pipecat_tracing_from_handshake(
    message: Mapping[str, Any],
    *,
    api_key: Optional[str] = None,
    service_name: str = "pipecat-agent",
) -> dict[str, Any]:
    """Like :func:`configure_pipecat_tracing`, using an EfficientAI handshake message.

    Only ``EFFICIENTAI_API_KEY`` has to be set on the agent; the call id, agent,
    workspace and OTLP endpoint come from the handshake.
    """
    handshake = parse_trace_handshake(message)
    if not handshake:
        raise ValueError("Message is not an EfficientAI trace handshake")

    otel = handshake.get("otel_correlation") or {}
    return configure_pipecat_tracing(
        call_short_id=handshake["call_short_id"],
        agent_id=str(handshake["agent_id"]) if handshake.get("agent_id") else None,
        workspace_id=str(handshake["workspace_id"]) if handshake.get("workspace_id") else None,
        otlp_endpoint=otel.get("otlp_endpoint"),
        api_key=api_key,
        service_name=service_name,
    )


setup_pipecat_worker_tracing = setup_worker_tracing
