"""Parse EfficientAI trace handshake messages from synthetic test transports."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from efficientai.integrations.efficientai_traces.setup import configure_pipecat_tracing

HANDSHAKE_TYPE = "efficientai_trace_handshake"
LEGACY_CALL_SHORT_ID_KEY = "efficientai_call_short_id"


def parse_trace_handshake(message: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize playground / session API handshake payloads."""
    if not isinstance(message, Mapping):
        return None

    if message.get("type") == HANDSHAKE_TYPE:
        call_short_id = message.get("call_short_id")
        if not call_short_id:
            return None
        return {
            "type": HANDSHAKE_TYPE,
            "call_short_id": str(call_short_id),
            "trace_id": message.get("trace_id"),
            "agent_id": message.get("agent_id"),
            "workspace_id": message.get("workspace_id"),
            "transport": message.get("transport"),
            "otel_correlation": dict(message.get("otel_correlation") or {}),
        }

    legacy_id = message.get(LEGACY_CALL_SHORT_ID_KEY)
    if legacy_id:
        return {
            "type": HANDSHAKE_TYPE,
            "call_short_id": str(legacy_id),
            "trace_id": message.get("trace_id"),
            "agent_id": message.get("agent_id"),
            "workspace_id": message.get("workspace_id"),
            "transport": message.get("transport"),
            "otel_correlation": dict(message.get("otel_correlation") or {}),
        }
    return None


def configure_pipecat_tracing_from_handshake(
    message: Mapping[str, Any],
    *,
    api_key: Optional[str] = None,
    service_name: str = "pipecat-agent",
) -> Dict[str, Any]:
    """
    Configure Pipecat OTLP export from an EfficientAI handshake message.

  Only ``EFFICIENTAI_API_KEY`` must be configured on the customer server (once).
  ``call_short_id``, ``agent_id``, ``workspace_id``, and OTLP endpoint come
  from the handshake automatically.
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
