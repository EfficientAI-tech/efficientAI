"""Production alert metrics from webhook call recordings and ClickHouse traces."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.api.v1.routes.observability import _resolve_call_duration_seconds
from app.models.database import CallRecording, CallRecordingSource
from app.models.enums import AlertAggregation, AlertMetricType
from app.services.clickhouse.client import clickhouse_enabled, get_client

_FAILED_CALL_EVENTS = frozenset(
    {"call_failed", "failed", "error", "busy", "no_answer", "canceled", "cancelled"}
)
_FAILED_PROVIDER_STATUSES = frozenset(
    {"busy", "no-answer", "no_answer", "canceled", "cancelled", "failed", "error"}
)
_SUCCESS_PROVIDER_STATUSES = frozenset({"completed", "hangup"})

_TRACES_TABLE = "call_traces FINAL"


def _agent_uuid_list(agent_ids: Optional[list]) -> Optional[List[UUID]]:
    if not agent_ids:
        return None
    out: List[UUID] = []
    for aid in agent_ids:
        out.append(UUID(aid) if isinstance(aid, str) else aid)
    return out


def _apply_numeric_agg(values: List[float], aggregation: str) -> Optional[float]:
    if not values:
        return None
    agg = (aggregation or "avg").lower()
    if agg in (AlertAggregation.SUM.value, "sum"):
        return float(sum(values))
    if agg in (AlertAggregation.AVG.value, "avg"):
        return float(sum(values) / len(values))
    if agg in (AlertAggregation.COUNT.value, "count"):
        return float(len(values))
    if agg in (AlertAggregation.MIN.value, "min"):
        return float(min(values))
    if agg in (AlertAggregation.MAX.value, "max"):
        return float(max(values))
    return None


def _production_calls_query(
    db: Session,
    organization_id: UUID,
    agent_ids: Optional[list],
    window_start: datetime,
):
    query = db.query(CallRecording).filter(
        and_(
            CallRecording.organization_id == organization_id,
            CallRecording.source == CallRecordingSource.WEBHOOK,
            CallRecording.created_at >= window_start,
        )
    )
    agent_uuid_list = _agent_uuid_list(agent_ids)
    if agent_uuid_list:
        query = query.filter(CallRecording.agent_id.in_(agent_uuid_list))
    return query


def _saved_provider_status(row: CallRecording) -> str:
    data = row.call_data if isinstance(row.call_data, dict) else {}
    last = data.get("last_event") if isinstance(data.get("last_event"), dict) else {}
    raw = str(last.get("CallStatus") or last.get("Event") or last.get("Status") or "")
    return raw.strip().lower().replace("_", "-")


def _call_outcome(row: CallRecording) -> str:
    """Classify a finished attempt. Vobiz stores call_ended for busy and no-answer too."""
    saved = _saved_provider_status(row)
    event = (row.call_event or "").strip().lower()
    if saved in _FAILED_PROVIDER_STATUSES or event in _FAILED_CALL_EVENTS:
        return "failed"
    if saved in _SUCCESS_PROVIDER_STATUSES or event in ("completed", "call_ended"):
        return "success"
    return "pending"


def compute_production_calls_metric(
    db: Session,
    organization_id: UUID,
    agent_ids: Optional[list],
    window_start: datetime,
    metric_type: str,
    aggregation: str,
) -> Optional[float]:
    query = _production_calls_query(db, organization_id, agent_ids, window_start)
    rows = query.all()
    if not rows:
        return None

    mtype = (metric_type or "").lower()
    if mtype in (AlertMetricType.NUMBER_OF_CALLS.value, "number_of_calls", "custom"):
        return float(len(rows))

    if mtype in (AlertMetricType.CALL_DURATION.value, "call_duration"):
        durations: List[float] = []
        for row in rows:
            call_data = row.call_data if isinstance(row.call_data, dict) else {}
            dur = _resolve_call_duration_seconds(call_data)
            if dur is not None and dur > 0:
                durations.append(dur)
        return _apply_numeric_agg(durations, aggregation)

    if mtype in (AlertMetricType.ERROR_RATE.value, "error_rate"):
        decided = [o for o in (_call_outcome(r) for r in rows) if o != "pending"]
        if not decided:
            return None
        failed = sum(1 for o in decided if o == "failed")
        return round((failed / len(decided)) * 100, 2)

    if mtype in (AlertMetricType.SUCCESS_RATE.value, "success_rate"):
        decided = [o for o in (_call_outcome(r) for r in rows) if o != "pending"]
        if not decided:
            return None
        ok = sum(1 for o in decided if o == "success")
        return round((ok / len(decided)) * 100, 2)

    return None


def _trace_latency_agg_sql(aggregation: str) -> tuple[str, str]:
    agg = (aggregation or "avg").lower()
    if agg in (AlertAggregation.MIN.value, "min"):
        return "min(response_latency_p50_ms)", "response_latency_p50_ms"
    if agg in (AlertAggregation.MAX.value, "max"):
        return "max(response_latency_p95_ms)", "response_latency_p95_ms"
    if agg in (AlertAggregation.SUM.value, "sum"):
        return "sum(response_latency_p90_ms)", "response_latency_p90_ms"
    if agg in (AlertAggregation.COUNT.value, "count"):
        return "count()", "response_latency_p90_ms"
    return "avg(response_latency_p90_ms)", "response_latency_p90_ms"


def compute_production_traces_metric(
    organization_id: UUID,
    agent_ids: Optional[list],
    window_start: datetime,
    metric_type: str,
    aggregation: str,
) -> Optional[float]:
    if not clickhouse_enabled():
        return None

    conditions = [
        "organization_id = {org_id:UUID}",
        "started_at >= {since:DateTime64(3)}",
        "evaluator_result_id IS NULL",
        "transport != 'websocket'",
    ]
    params: Dict[str, Any] = {
        "org_id": organization_id,
        "since": window_start.replace(tzinfo=None),
    }
    agent_uuid_list = _agent_uuid_list(agent_ids)
    if agent_uuid_list:
        conditions.append("agent_id IN {agent_ids:Array(UUID)}")
        params["agent_ids"] = agent_uuid_list

    where = " AND ".join(conditions)
    mtype = (metric_type or "").lower()
    agg = (aggregation or "avg").lower()

    client = get_client()

    if mtype in (AlertMetricType.NUMBER_OF_CALLS.value, "number_of_calls", "custom"):
        row = client.query(
            f"SELECT count() FROM {_TRACES_TABLE} WHERE {where}",
            parameters=params,
        ).first_row
        count = float(row[0]) if row else 0.0
        return None if count == 0 else count

    if mtype in (AlertMetricType.CALL_DURATION.value, "call_duration"):
        if agg == "count":
            row = client.query(
                f"""
                SELECT count()
                FROM {_TRACES_TABLE}
                WHERE {where} AND ended_at IS NOT NULL
                """,
                parameters=params,
            ).first_row
            count = float(row[0]) if row else 0.0
            return None if count == 0 else count
        col = "avg" if agg == "avg" else agg
        if col not in ("avg", "min", "max", "sum"):
            col = "avg"
        row = client.query(
            f"""
            SELECT {col}(dateDiff('second', started_at, ended_at))
            FROM {_TRACES_TABLE}
            WHERE {where} AND ended_at IS NOT NULL
            """,
            parameters=params,
        ).first_row
        if row and row[0] is not None:
            return float(row[0])
        return None

    if mtype in (AlertMetricType.LATENCY.value, "latency"):
        agg_expr, latency_col = _trace_latency_agg_sql(aggregation)
        row = client.query(
            f"""
            SELECT {agg_expr}
            FROM {_TRACES_TABLE}
            WHERE {where} AND {latency_col} IS NOT NULL
            """,
            parameters=params,
        ).first_row
        if row and row[0] is not None:
            return round(float(row[0]), 2)
        return None

    if mtype in (AlertMetricType.ERROR_RATE.value, "error_rate"):
        row = client.query(
            f"""
            SELECT
                countIf(status IN ('closed', 'finalized', 'closing')) AS total,
                countIf(
                    status IN ('closed', 'finalized', 'closing')
                    AND failure_flags IS NOT NULL
                    AND failure_flags != ''
                    AND failure_flags != '[]'
                ) AS failed
            FROM {_TRACES_TABLE}
            WHERE {where}
            """,
            parameters=params,
        ).first_row
        if not row or not row[0]:
            return None
        total, failed = int(row[0]), int(row[1])
        return round((failed / total) * 100, 2)

    if mtype in (AlertMetricType.SUCCESS_RATE.value, "success_rate"):
        row = client.query(
            f"""
            SELECT
                countIf(status IN ('closed', 'finalized', 'closing')) AS total,
                countIf(
                    status IN ('closed', 'finalized', 'closing')
                    AND (
                        failure_flags IS NULL
                        OR failure_flags = ''
                        OR failure_flags = '[]'
                    )
                ) AS ok
            FROM {_TRACES_TABLE}
            WHERE {where}
            """,
            parameters=params,
        ).first_row
        if not row or not row[0]:
            return None
        total, ok = int(row[0]), int(row[1])
        return round((ok / total) * 100, 2)

    return None
