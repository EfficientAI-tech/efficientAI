"""Correlation ids shared between EfficientAI dial-out and customer Pipecat ingest."""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

# OTLP HTTP headers (customer → EfficientAI)
OTLP_HEADER_API_KEY = "X-API-Key"
OTLP_HEADER_CALL_SHORT_ID = "X-EfficientAI-Call-Short-Id"
OTLP_HEADER_RUN_ID = "X-EfficientAI-Run-Id"

# SIP headers on outbound INVITE (EfficientAI → customer PSTN/SIP)
# Vobiz forwards X-VH-* ; Plivo prefixes custom keys with X-PH-
SIP_VH_CALL_SHORT_ID = "X-VH-EfficientAI-Call-Short-Id"
SIP_VH_RUN_ID = "X-VH-EfficientAI-Run-Id"
SIP_PLIVO_CALL_SHORT_ID = "EfficientAI-Call-Short-Id"
SIP_PLIVO_RUN_ID = "EfficientAI-Run-Id"

# Span / resource attributes
ATTR_CALL_SHORT_ID = "efficientai.call_short_id"
ATTR_RUN_ID = "efficientai.evaluator_result_id"
ATTR_AGENT_ID = "efficientai.agent_id"
ATTR_WORKSPACE_ID = "efficientai.workspace_id"
ATTR_ENVIRONMENT = "efficientai.environment"
ATTR_TRANSPORT = "efficientai.transport"

_CALL_SHORT_ID_RE = re.compile(r"^\d{6}$")

_HEADER_ALIASES_CALL_SHORT_ID = (
    OTLP_HEADER_CALL_SHORT_ID,
    SIP_VH_CALL_SHORT_ID,
    "X-PH-EfficientAI-Call-Short-Id",
    "SipHeader_X-VH-EfficientAI-Call-Short-Id",
    "SipHeader_X-PH-EfficientAI-Call-Short-Id",
    "X-EfficientAI-Call-Short-Id",
    "EfficientAI-Call-Short-Id",
    "efficientai.call_short_id",
    "Call-Short-Id",
    "call_short_id",
    "X-Custom-Call-Short-Id",
)


def _normalize_header_key(key: str) -> str:
    return key.strip().lower().replace("_", "-")


def _lookup(mapping: Mapping[str, Any], *candidates: str) -> Optional[str]:
    if not mapping:
        return None
    normalized = {_normalize_header_key(str(k)): v for k, v in mapping.items()}
    for name in candidates:
        val = normalized.get(_normalize_header_key(name))
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _valid_call_short_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = str(value).strip()
    if _CALL_SHORT_ID_RE.match(cleaned):
        return cleaned
    return None


def extract_call_short_id(
    *,
    sip_headers: Optional[Mapping[str, Any]] = None,
    webhook_params: Optional[Mapping[str, Any]] = None,
    custom_params: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Resolve EfficientAI 6-digit call id from inbound telephony metadata."""
    for mapping in (sip_headers, webhook_params, custom_params):
        found = _lookup(mapping, *_HEADER_ALIASES_CALL_SHORT_ID)
        valid = _valid_call_short_id(found)
        if valid:
            return valid
    return None


def build_outbound_sip_headers(
    *,
    call_short_id: str,
    evaluator_result_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, str]:
    """Headers to attach on Vobiz/Plivo outbound INVITE for customer-side correlation."""
    cid = _valid_call_short_id(call_short_id)
    if not cid:
        raise ValueError("call_short_id must be a 6-digit string")

    headers: Dict[str, str] = {
        SIP_VH_CALL_SHORT_ID: cid,
        SIP_PLIVO_CALL_SHORT_ID: cid,
    }
    if evaluator_result_id:
        headers[SIP_VH_RUN_ID] = str(evaluator_result_id)
        headers[SIP_PLIVO_RUN_ID] = str(evaluator_result_id)
    if agent_id:
        headers["X-VH-EfficientAI-Agent-Id"] = str(agent_id)
        headers["EfficientAI-Agent-Id"] = str(agent_id)
    return headers


def format_plivo_sip_headers(headers: Mapping[str, str]) -> str:
    """Plivo/Vobiz REST API expects comma-separated key=value pairs."""
    return ",".join(f"{k}={v}" for k, v in headers.items())


def otlp_export_headers(
    *,
    api_key: str,
    call_short_id: Optional[str] = None,
    evaluator_result_id: Optional[str] = None,
) -> Dict[str, str]:
    headers = {OTLP_HEADER_API_KEY: api_key}
    cid = _valid_call_short_id(call_short_id)
    if cid:
        headers[OTLP_HEADER_CALL_SHORT_ID] = cid
    if evaluator_result_id:
        headers[OTLP_HEADER_RUN_ID] = str(evaluator_result_id)
    return headers


def span_correlation_attributes(
    *,
    call_short_id: Optional[str] = None,
    evaluator_result_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    transport: Optional[str] = None,
    environment: str = "pre_prod",
) -> Dict[str, str]:
    attrs: Dict[str, str] = {ATTR_ENVIRONMENT: environment}
    cid = _valid_call_short_id(call_short_id)
    if cid:
        attrs[ATTR_CALL_SHORT_ID] = cid
    if evaluator_result_id:
        attrs[ATTR_RUN_ID] = str(evaluator_result_id)
    if agent_id:
        attrs[ATTR_AGENT_ID] = str(agent_id)
    if workspace_id:
        attrs[ATTR_WORKSPACE_ID] = str(workspace_id)
    if transport:
        attrs[ATTR_TRANSPORT] = str(transport)
    return attrs
