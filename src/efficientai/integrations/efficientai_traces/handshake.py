"""Moved to :mod:`efficientai_sdk.tracing.handshake` and
:mod:`efficientai_sdk.integrations.pipecat`. Kept so existing imports keep working."""

from efficientai_sdk.integrations.pipecat import configure_pipecat_tracing_from_handshake
from efficientai_sdk.tracing.handshake import (
    HANDSHAKE_TYPE,
    LEGACY_CALL_SHORT_ID_KEY,
    parse_trace_handshake,
)

__all__ = [
    "HANDSHAKE_TYPE",
    "LEGACY_CALL_SHORT_ID_KEY",
    "configure_pipecat_tracing_from_handshake",
    "parse_trace_handshake",
]
