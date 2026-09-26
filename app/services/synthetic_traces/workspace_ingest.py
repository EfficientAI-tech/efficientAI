"""Resolve workspace_id for OTLP ingest (API-key bots without X-Workspace-Id)."""

from __future__ import annotations

from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.services.synthetic_traces.otlp_ingest import parse_otlp_body
from app.services.synthetic_traces.otlp_mapper import extract_correlation_ids
from app.services.synthetic_traces.trace_service import get_trace_by_call_short_id


def peek_otlp_correlation(
    body: bytes,
    content_type: str,
) -> Tuple[Optional[str], Optional[UUID]]:
    """Lightweight parse for call_short_id and workspace_id from an OTLP batch."""
    if not body:
        return None, None
    try:
        spans, _fmt = parse_otlp_body(body, content_type)
    except Exception:
        return None, None
    if not spans:
        return None, None
    correlation = extract_correlation_ids(spans)
    call_short_id = correlation.get("call_short_id")
    workspace_id: Optional[UUID] = None
    ws_raw = correlation.get("workspace_id")
    if ws_raw:
        try:
            workspace_id = UUID(str(ws_raw).strip())
        except (ValueError, TypeError):
            workspace_id = None
    return call_short_id, workspace_id


def resolve_otlp_ingest_workspace_id(
    db: Session,
    *,
    organization_id: UUID,
    request_workspace_id: UUID,
    principal: Principal,
    header_call_short_id: Optional[str] = None,
    body: Optional[bytes] = None,
    content_type: str = "",
) -> UUID:
    """
    Pick the workspace for OTLP ingest.

    Session mint uses X-Workspace-Id; span export must land in the same workspace.
    When the OTLP HTTP request omits X-Workspace-Id, API-key auth falls back to the
    org default workspace — reconcile using call_short_id / span attributes first.
    """
    call_short_id = (header_call_short_id or "").strip() or None
    span_workspace_id: Optional[UUID] = None
    if body:
        peeked_short, peeked_ws = peek_otlp_correlation(body, content_type)
        if not call_short_id and peeked_short:
            call_short_id = peeked_short
        if peeked_ws is not None:
            span_workspace_id = peeked_ws

    if call_short_id:
        trace = get_trace_by_call_short_id(
            db,
            organization_id=organization_id,
            call_short_id=call_short_id,
            workspace_id=None,
        )
        if trace is not None and trace.workspace_id is not None:
            return trace.workspace_id

    if span_workspace_id is not None:
        return span_workspace_id

    return request_workspace_id
