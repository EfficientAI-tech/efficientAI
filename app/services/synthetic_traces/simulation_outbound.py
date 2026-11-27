"""Correlation ids EfficientAI sends to the agent under test during a simulation."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.services.synthetic_traces import ch_trace_ops
from app.services.synthetic_traces.trace_service import (
    get_trace_for_result,
    open_trace_session,
)

HEADER_CALL_SHORT_ID = "X-EfficientAI-Call-Short-Id"
HEADER_RUN_ID = "X-EfficientAI-Run-Id"
HANDSHAKE_TYPE = "efficientai_trace_handshake"


def correlation_http_headers(correlation: dict[str, Any]) -> dict[str, str]:
    headers = {HEADER_CALL_SHORT_ID: str(correlation["call_short_id"])}
    run_id = correlation.get("evaluator_result_id")
    if run_id:
        headers[HEADER_RUN_ID] = str(run_id)
    return headers


def trace_handshake_message(correlation: dict[str, Any]) -> dict[str, Any]:
    call_short_id = str(correlation["call_short_id"])
    run_id = correlation.get("evaluator_result_id")
    attributes = {"efficientai.call_short_id": call_short_id}
    if run_id:
        attributes["efficientai.evaluator_result_id"] = str(run_id)
    return {
        "type": HANDSHAKE_TYPE,
        "call_short_id": call_short_id,
        "agent_id": correlation.get("agent_id"),
        "workspace_id": correlation.get("workspace_id"),
        "transport": correlation.get("transport"),
        "otel_correlation": {"suggested_span_attributes": attributes},
    }


def handshake_enabled(config: Optional[dict[str, Any]]) -> bool:
    """Send the extra handshake frame only when the agent opts in.

    Existing WebSocket servers expect one request frame per turn, so a missing
    setting stays off.
    """
    if not config:
        return False
    flag = config.get("efficientai_trace_handshake_enabled")
    if isinstance(flag, str):
        return flag.strip().lower() in {"1", "true", "yes", "on"}
    return flag is True


def ensure_simulation_correlation(
    db: Session,
    evaluator_result: Any,
    *,
    transport: str,
) -> Optional[dict[str, Any]]:
    """Open or reuse the trace for this simulation result.

    Returns None when the result has no workspace, or when opening the trace fails.
    The simulation itself should still run.
    """
    if evaluator_result is None:
        return None
    organization_id = getattr(evaluator_result, "organization_id", None)
    workspace_id = getattr(evaluator_result, "workspace_id", None)
    result_id = getattr(evaluator_result, "id", None)
    if not organization_id or not workspace_id or not result_id:
        return None

    try:
        trace = get_trace_for_result(
            db,
            organization_id=organization_id,
            evaluator_result_id=result_id,
            workspace_id=workspace_id,
            auto_close=False,
        )
        if not trace or not getattr(trace, "call_short_id", None):
            agent_id = getattr(evaluator_result, "agent_id", None)
            trace = open_trace_session(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agent_id=agent_id if isinstance(agent_id, UUID) else None,
                evaluator_result_id=result_id,
                transport=transport,
            )
        if trace and transport in ("websocket", "custom"):
            aggs = dict(getattr(trace, "component_aggregates", None) or {})
            if aggs.get("session_modality") not in ("chat", "voice"):
                aggs["session_modality"] = "chat"
                trace.component_aggregates = aggs
                if ch_trace_ops.use_ch():
                    from app.services.synthetic_traces.ch_trace_ops import upsert_trace_header

                    upsert_trace_header(trace)
                else:
                    db.commit()
                    db.refresh(trace)
    except Exception as exc:
        logger.warning("EfficientAI simulation trace was not opened: {}", exc)
        return None

    call_short_id = getattr(trace, "call_short_id", None)
    if not call_short_id:
        return None
    agent_id = getattr(evaluator_result, "agent_id", None)
    return {
        "call_short_id": str(call_short_id),
        "evaluator_result_id": str(result_id),
        "agent_id": str(agent_id) if agent_id else None,
        "workspace_id": str(workspace_id),
        "transport": transport,
    }
