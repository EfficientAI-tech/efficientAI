"""Merged Calls page feed: telephony webhook calls + OTLP traces with server pagination."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.database import Agent, CallRecording, CallRecordingSource
from app.services.synthetic_traces.trace_service import (
    default_trace_list_since,
    enrich_trace_summaries,
    list_traces,
)

_LIVE_CALL_EVENTS = frozenset(
    {
        "outbound_initiated",
        "ringing",
        "call_started",
        "call_in_progress",
        "in-progress",
        "answered",
    }
)


def _obs_base_query(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
):
    return db.query(CallRecording).filter(
        CallRecording.organization_id == organization_id,
        CallRecording.workspace_id == workspace_id,
        CallRecording.source == CallRecordingSource.WEBHOOK,
        CallRecording.evaluator_result_id.is_(None),
    )


def _apply_obs_event_filter(query, event_filter: str):
    if event_filter == "call_ended":
        return query.filter(CallRecording.call_event == "call_ended")
    if event_filter == "call_started":
        return query.filter(CallRecording.call_event == "call_started")
    if event_filter == "other":
        return query.filter(
            or_(
                CallRecording.call_event.is_(None),
                and_(
                    CallRecording.call_event != "call_ended",
                    CallRecording.call_event != "call_started",
                ),
            )
        )
    return query


def _apply_obs_search(query, search: Optional[str]):
    if not search or not search.strip():
        return query
    pattern = f"%{search.strip()}%"
    return query.outerjoin(Agent, Agent.id == CallRecording.agent_id).filter(
        or_(
            CallRecording.call_short_id.ilike(pattern),
            CallRecording.provider_call_id.ilike(pattern),
            Agent.name.ilike(pattern),
        )
    )


def _trace_rows_match_search(row: Any, search: Optional[str]) -> bool:
    if not search or not search.strip():
        return True
    q = search.strip().lower()
    call_short_id = (getattr(row, "call_short_id", None) or "").lower()
    trace_id = str(getattr(row, "id", "")).lower()
    transport = (getattr(row, "transport", None) or "").lower()
    return q in call_short_id or q in trace_id or q in transport


def _obs_sort_key(recording: CallRecording) -> datetime:
    return recording.created_at or datetime.min.replace(tzinfo=None)


def _trace_sort_key(trace: Any) -> datetime:
    started = getattr(trace, "started_at", None)
    return started or datetime.min.replace(tzinfo=None)


def _count_obs_summary(db: Session, obs_query) -> Tuple[int, int]:
    total = obs_query.count()
    live = (
        obs_query.filter(CallRecording.call_event.in_(tuple(_LIVE_CALL_EVENTS))).count()
        if total
        else 0
    )
    return total, live


def _count_traces(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    *,
    status: Optional[str],
) -> int:
    since = default_trace_list_since()
    _, total, _, _ = list_traces(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        skip=0,
        limit=1,
        status=status,
        since=since,
        exclude_playground_websocket=True,
    )
    return int(total or 0)


def list_calls_hub_page(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    skip: int,
    limit: int,
    trace_status: Optional[str] = None,
    search: Optional[str] = None,
    event_filter: str = "all",
    serialize_obs_call,
) -> Tuple[List[Dict[str, Any]], Dict[str, int], int]:
    """
    Return merged page items, summary counts, and filtered total row count.

    Each item: {"kind": "obs"|"trace", "sort_at": iso, "obs"?: dict, "trace"?: dict}
    """
    since = default_trace_list_since()
    window = skip + limit

    obs_query = _obs_base_query(db, organization_id=organization_id, workspace_id=workspace_id)
    obs_query = _apply_obs_event_filter(obs_query, event_filter)
    obs_query = _apply_obs_search(obs_query, search)
    obs_total, obs_live = _count_obs_summary(db, obs_query)
    obs_base = _obs_base_query(db, organization_id=organization_id, workspace_id=workspace_id)
    obs_base = _apply_obs_search(obs_base, search)
    obs_event_total = obs_base.count()
    obs_ended = _apply_obs_event_filter(obs_base, "call_ended").count()
    obs_started = _apply_obs_event_filter(obs_base, "call_started").count()
    obs_other = max(0, int(obs_event_total) - int(obs_ended) - int(obs_started))

    trace_list_status = None if not trace_status or trace_status == "all" else trace_status
    trace_rows_window, trace_filtered_total, _, _ = list_traces(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        skip=0,
        limit=window,
        status=trace_list_status,
        since=since,
        exclude_playground_websocket=True,
    )
    if search and search.strip():
        trace_rows_window = [r for r in trace_rows_window if _trace_rows_match_search(r, search)]
    trace_total = int(trace_filtered_total or 0)
    if search and search.strip():
        trace_total = len(trace_rows_window)

    traces_all = _count_traces(db, organization_id, workspace_id, status=None)
    traces_open = _count_traces(db, organization_id, workspace_id, status="open")
    traces_closed = _count_traces(db, organization_id, workspace_id, status="closed")

    obs_rows = (
        obs_query.order_by(CallRecording.created_at.desc()).limit(window).all()
    )
    from app.services.live_entity_storage import hydrate_call_recordings

    hydrate_call_recordings(obs_rows)
    agent_ids = [cr.agent_id for cr in obs_rows if cr.agent_id]
    agents_by_id: Dict[UUID, Agent] = {}
    if agent_ids:
        agents_by_id = {a.id: a for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()}

    merged: List[Tuple[datetime, str, Any]] = []
    for cr in obs_rows:
        merged.append((_obs_sort_key(cr), "obs", cr))
    for tr in trace_rows_window:
        merged.append((_trace_sort_key(tr), "trace", tr))

    merged.sort(key=lambda row: row[0], reverse=True)
    page_slice = merged[skip : skip + limit]

    trace_rows_for_enrich = [row[2] for row in page_slice if row[1] == "trace"]
    enriched = enrich_trace_summaries(db, trace_rows_for_enrich)
    enriched_by_id = {str(item.get("id")): item for item in enriched}

    items: List[Dict[str, Any]] = []
    for sort_at, kind, payload in page_slice:
        sort_iso = sort_at.isoformat() if sort_at else None
        if kind == "obs":
            agent = agents_by_id.get(payload.agent_id) if payload.agent_id else None
            items.append(
                {
                    "kind": "obs",
                    "sort_at": sort_iso,
                    "obs": serialize_obs_call(payload, agent=agent),
                }
            )
        else:
            tid = str(getattr(payload, "id", ""))
            trace_payload = enriched_by_id.get(tid)
            if trace_payload is None:
                trace_payload = {
                    "id": getattr(payload, "id", None),
                    "call_short_id": getattr(payload, "call_short_id", None),
                    "transport": getattr(payload, "transport", None),
                    "status": getattr(payload, "status", None),
                    "turn_count": getattr(payload, "turn_count", 0),
                    "started_at": sort_iso,
                    "span_count": getattr(payload, "span_count", 0),
                    "derive_pending": getattr(payload, "derive_pending", False),
                }
            items.append({"kind": "trace", "sort_at": sort_iso, "trace": trace_payload})

    if trace_list_status == "open":
        filtered_total = int(obs_total) + int(traces_open)
    elif trace_list_status == "closed":
        filtered_total = int(obs_total) + int(traces_closed)
    else:
        filtered_total = int(obs_total) + int(traces_all if not (search and search.strip()) else trace_total)

    summary = {
        "total": int(obs_total) + int(traces_all),
        "obs_total": int(obs_total),
        "obs_live": int(obs_live),
        "obs_ended": int(obs_ended),
        "obs_started": int(obs_started),
        "obs_other": int(obs_other),
        "traces_open": int(traces_open),
        "traces_closed": int(traces_closed),
    }
    return items, summary, filtered_total
