"""ClickHouse + Redis store for call traces (S3 WAL serving layer)."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

import redis
from loguru import logger

from app.config import settings
from app.services.clickhouse.client import clickhouse_enabled, get_client

_redis_client: Optional[redis.Redis] = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_ch(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _ch_to_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, default=str)


def _json_loads(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


OTEL_TRACE_ID_ATTR = "efficientai.otel_trace_id"


def _resolve_otel_trace_id(
    span_trace_id: Any,
    attributes: Dict[str, Any],
    fallback_trace_id: str,
) -> str:
    if span_trace_id:
        return str(span_trace_id)
    stored = attributes.get(OTEL_TRACE_ID_ATTR)
    if stored:
        return str(stored)
    return fallback_trace_id


@dataclass
class TraceRecord:
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    evaluator_result_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    persona_id: Optional[UUID] = None
    scenario_id: Optional[UUID] = None
    evaluator_id: Optional[UUID] = None
    call_recording_id: Optional[UUID] = None
    call_short_id: Optional[str] = None
    environment: str = "pre_prod"
    provider_platform: Optional[str] = None
    transport: str = "phone"
    tier: str = "black_box"
    status: str = "open"
    started_at: datetime = field(default_factory=_utcnow)
    ended_at: Optional[datetime] = None
    turn_count: int = 0
    response_latency_p50_ms: Optional[float] = None
    response_latency_p90_ms: Optional[float] = None
    response_latency_p95_ms: Optional[float] = None
    component_aggregates: Optional[Dict[str, Any]] = None
    failure_flags: Optional[Dict[str, Any]] = None
    spans_s3_key: Optional[str] = None
    spans_storage: str = "clickhouse"
    span_count: int = 0
    last_span_at: Optional[datetime] = None
    derive_pending: bool = False
    turns: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


def _row_to_trace(row: tuple, columns: List[str]) -> TraceRecord:
    data = dict(zip(columns, row))
    return TraceRecord(
        id=UUID(str(data["trace_uuid"])),
        organization_id=UUID(str(data["organization_id"])),
        workspace_id=UUID(str(data["workspace_id"])),
        evaluator_result_id=UUID(str(data["evaluator_result_id"])) if data.get("evaluator_result_id") else None,
        agent_id=UUID(str(data["agent_id"])) if data.get("agent_id") else None,
        persona_id=UUID(str(data["persona_id"])) if data.get("persona_id") else None,
        scenario_id=UUID(str(data["scenario_id"])) if data.get("scenario_id") else None,
        evaluator_id=UUID(str(data["evaluator_id"])) if data.get("evaluator_id") else None,
        call_recording_id=UUID(str(data["call_recording_id"])) if data.get("call_recording_id") else None,
        call_short_id=data.get("call_short_id"),
        environment=data.get("environment") or "pre_prod",
        provider_platform=data.get("provider_platform"),
        transport=data.get("transport") or "phone",
        tier=data.get("tier") or "black_box",
        status=data.get("status") or "open",
        started_at=_ch_to_dt(data.get("started_at")) or _utcnow(),
        ended_at=_ch_to_dt(data.get("ended_at")),
        turn_count=int(data.get("turn_count") or 0),
        response_latency_p50_ms=data.get("response_latency_p50_ms"),
        response_latency_p90_ms=data.get("response_latency_p90_ms"),
        response_latency_p95_ms=data.get("response_latency_p95_ms"),
        component_aggregates=_json_loads(data.get("component_aggregates")),
        failure_flags=_json_loads(data.get("failure_flags")),
        spans_s3_key=data.get("spans_s3_key"),
        spans_storage=data.get("spans_storage") or "clickhouse",
        span_count=int(data.get("span_count") or 0),
        last_span_at=_ch_to_dt(data.get("last_span_at")),
        turns=_json_loads(data.get("turns")),
        updated_at=_ch_to_dt(data.get("updated_at")),
    )


_TRACE_COLUMNS = [
    "trace_uuid",
    "organization_id",
    "workspace_id",
    "evaluator_result_id",
    "agent_id",
    "persona_id",
    "scenario_id",
    "evaluator_id",
    "call_recording_id",
    "call_short_id",
    "environment",
    "provider_platform",
    "transport",
    "tier",
    "status",
    "started_at",
    "ended_at",
    "turn_count",
    "response_latency_p50_ms",
    "response_latency_p90_ms",
    "response_latency_p95_ms",
    "component_aggregates",
    "failure_flags",
    "spans_s3_key",
    "spans_storage",
    "span_count",
    "last_span_at",
    "turns",
    "updated_at",
]


def _select_trace_query(where_clause: str) -> str:
    cols = ", ".join(_TRACE_COLUMNS)
    return f"SELECT {cols} FROM call_traces FINAL WHERE {where_clause} LIMIT 1"


def upsert_trace_header(trace: TraceRecord) -> None:
    client = get_client()
    now = _utcnow()
    row = [
        trace.id,
        trace.organization_id,
        trace.workspace_id,
        trace.evaluator_result_id,
        trace.agent_id,
        trace.persona_id,
        trace.scenario_id,
        trace.evaluator_id,
        trace.call_recording_id,
        trace.call_short_id,
        trace.environment,
        trace.provider_platform,
        trace.transport,
        trace.tier,
        trace.status,
        _dt_to_ch(trace.started_at),
        _dt_to_ch(trace.ended_at) if trace.ended_at else None,
        trace.turn_count,
        trace.response_latency_p50_ms,
        trace.response_latency_p90_ms,
        trace.response_latency_p95_ms,
        _json_dumps(trace.component_aggregates),
        _json_dumps(trace.failure_flags),
        trace.spans_s3_key,
        trace.spans_storage,
        trace.span_count,
        _dt_to_ch(trace.last_span_at) if trace.last_span_at else None,
        _json_dumps(trace.turns),
        _dt_to_ch(now),
    ]
    client.insert("call_traces", [row], column_names=_TRACE_COLUMNS)


def get_trace_by_id(
    *,
    organization_id: UUID,
    trace_id: UUID,
    workspace_id: Optional[UUID] = None,
) -> Optional[TraceRecord]:
    where = "trace_uuid = {trace_id:UUID} AND organization_id = {org_id:UUID}"
    params = {"trace_id": trace_id, "org_id": organization_id}
    if workspace_id is not None:
        where += " AND workspace_id = {ws_id:UUID}"
        params["ws_id"] = workspace_id
    result = get_client().query(_select_trace_query(where), parameters=params)
    if not result.result_rows:
        return None
    return _row_to_trace(result.result_rows[0], list(result.column_names))


def get_trace_by_uuid(trace_uuid: UUID) -> Optional[TraceRecord]:
    result = get_client().query(
        _select_trace_query("trace_uuid = {trace_id:UUID}"),
        parameters={"trace_id": trace_uuid},
    )
    if not result.result_rows:
        return None
    return _row_to_trace(result.result_rows[0], list(result.column_names))


def get_trace_by_evaluator_result_id(
    *,
    organization_id: UUID,
    evaluator_result_id: UUID,
    workspace_id: Optional[UUID] = None,
) -> Optional[TraceRecord]:
    where = (
        "organization_id = {org_id:UUID} AND evaluator_result_id = {er_id:UUID}"
    )
    params: Dict[str, Any] = {"org_id": organization_id, "er_id": evaluator_result_id}
    if workspace_id is not None:
        where += " AND workspace_id = {ws_id:UUID}"
        params["ws_id"] = workspace_id
    query = (
        f"SELECT {', '.join(_TRACE_COLUMNS)} FROM call_traces FINAL "
        f"WHERE {where} ORDER BY started_at DESC LIMIT 1"
    )
    result = get_client().query(query, parameters=params)
    if not result.result_rows:
        return None
    return _row_to_trace(result.result_rows[0], list(result.column_names))


def get_trace_by_call_short_id(
    *,
    organization_id: UUID,
    call_short_id: str,
    workspace_id: Optional[UUID] = None,
) -> Optional[TraceRecord]:
    where = (
        "organization_id = {org_id:UUID} AND call_short_id = {short_id:String}"
    )
    params = {"org_id": organization_id, "short_id": call_short_id}
    if workspace_id is not None:
        where += " AND workspace_id = {ws_id:UUID}"
        params["ws_id"] = workspace_id
    query = (
        f"SELECT {', '.join(_TRACE_COLUMNS)} FROM call_traces FINAL "
        f"WHERE {where} ORDER BY started_at DESC LIMIT 1"
    )
    result = get_client().query(query, parameters=params)
    if not result.result_rows:
        return None
    return _row_to_trace(result.result_rows[0], list(result.column_names))


def call_short_id_exists(call_short_id: str) -> bool:
    result = get_client().query(
        "SELECT 1 FROM call_traces FINAL WHERE call_short_id = {short_id:String} LIMIT 1",
        parameters={"short_id": call_short_id},
    )
    return bool(result.result_rows)


def list_traces(
    *,
    organization_id: UUID,
    workspace_id: UUID,
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    cursor: Optional[str] = None,
    since: Optional[datetime] = None,
) -> tuple[List[TraceRecord], Optional[int], Optional[str], bool]:
    client = get_client()
    conditions = [
        "organization_id = {org_id:UUID}",
        "workspace_id = {ws_id:UUID}",
    ]
    params: Dict[str, Any] = {"org_id": organization_id, "ws_id": workspace_id}
    if since is not None:
        conditions.append("started_at >= {since:DateTime64(3)}")
        params["since"] = _dt_to_ch(since)
    if status:
        if status == "closed":
            conditions.append("status IN ('closed', 'finalized', 'closing')")
        else:
            conditions.append("status = {status:String}")
            params["status"] = status
    where = " AND ".join(conditions)
    cols = ", ".join(_TRACE_COLUMNS)

    if cursor:
        started_at, trace_id = _decode_trace_cursor(cursor)
        params["cursor_started"] = _dt_to_ch(started_at)
        params["cursor_id"] = trace_id
        cursor_where = (
            f"{where} AND (started_at < {{cursor_started:DateTime64(3)}} "
            f"OR (started_at = {{cursor_started:DateTime64(3)}} AND trace_uuid < {{cursor_id:UUID}}))"
        )
        query = (
            f"SELECT {cols} FROM call_traces FINAL WHERE {cursor_where} "
            f"ORDER BY started_at DESC, trace_uuid DESC LIMIT {limit + 1}"
        )
        result = client.query(query, parameters=params)
        rows = [_row_to_trace(r, list(result.column_names)) for r in result.result_rows]
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]
        next_cursor = _encode_trace_cursor(rows[-1]) if has_more and rows else None
        return rows, None, next_cursor, has_more

    count_result = client.query(
        f"SELECT count() FROM call_traces FINAL WHERE {where}",
        parameters=params,
    )
    total = int(count_result.result_rows[0][0]) if count_result.result_rows else 0
    query = (
        f"SELECT {cols} FROM call_traces FINAL WHERE {where} "
        f"ORDER BY started_at DESC LIMIT {limit} OFFSET {skip}"
    )
    result = client.query(query, parameters=params)
    rows = [_row_to_trace(r, list(result.column_names)) for r in result.result_rows]
    return rows, total, None, False


def _encode_trace_cursor(trace: TraceRecord) -> str:
    started = trace.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    payload = {"started_at": started.isoformat(), "id": str(trace.id)}
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _decode_trace_cursor(cursor: str) -> Tuple[datetime, UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    payload = json.loads(raw.decode("utf-8"))
    started_at = datetime.fromisoformat(payload["started_at"])
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at, UUID(payload["id"])


def insert_observations(
    *,
    workspace_id: UUID,
    trace_uuid: UUID,
    spans: List[Dict[str, Any]],
) -> int:
    if not spans:
        return 0
    client = get_client()
    rows = []
    for span in spans:
        span_id = str(span.get("span_id") or "")
        if not span_id:
            continue
        attrs = dict(span.get("attributes") or {})
        trace_id = span.get("trace_id")
        if trace_id and OTEL_TRACE_ID_ATTR not in attrs:
            attrs[OTEL_TRACE_ID_ATTR] = str(trace_id)
        rows.append(
            [
                workspace_id,
                trace_uuid,
                span_id,
                span.get("parent_span_id"),
                str(span.get("name") or ""),
                span.get("kind"),
                int(span.get("start_time_unix_nano") or 0),
                int(span.get("end_time_unix_nano") or 0),
                _json_dumps(attrs),
                _json_dumps(span.get("events") or []),
                span.get("status", {}).get("code") if isinstance(span.get("status"), dict) else span.get("status_code"),
                span.get("status", {}).get("message") if isinstance(span.get("status"), dict) else span.get("status_message"),
            ]
        )
    if not rows:
        return 0
    client.insert(
        "trace_observations",
        rows,
        column_names=[
            "workspace_id",
            "trace_uuid",
            "span_id",
            "parent_span_id",
            "name",
            "kind",
            "start_time_unix_nano",
            "end_time_unix_nano",
            "attributes",
            "events",
            "status_code",
            "status_message",
        ],
    )
    return len(rows)


def get_observations(trace_uuid: UUID) -> List[Dict[str, Any]]:
    result = get_client().query(
        """
        SELECT span_id, parent_span_id, name, kind, start_time_unix_nano,
               end_time_unix_nano, attributes, events, status_code, status_message
        FROM trace_observations
        WHERE trace_uuid = {trace_id:UUID}
        ORDER BY start_time_unix_nano ASC
        """,
        parameters={"trace_id": trace_uuid},
    )
    fallback_trace_id = trace_uuid.hex
    spans: List[Dict[str, Any]] = []
    for row in result.result_rows:
        attrs = _json_loads(row[6]) or {}
        events = _json_loads(row[7]) or []
        status_code = row[8]
        status_message = row[9]
        span: Dict[str, Any] = {
            "trace_id": _resolve_otel_trace_id(None, attrs, fallback_trace_id),
            "span_id": row[0],
            "parent_span_id": row[1],
            "name": row[2],
            "kind": row[3],
            "start_time_unix_nano": row[4],
            "end_time_unix_nano": row[5],
            "attributes": attrs,
            "events": events,
        }
        if status_code:
            span["status"] = {"code": status_code, "message": status_message}
        spans.append(span)
    return spans


def list_idle_open_traces(cutoff: datetime, limit: int = 200) -> List[TraceRecord]:
    result = get_client().query(
        f"""
        SELECT {', '.join(_TRACE_COLUMNS)}
        FROM call_traces FINAL
        WHERE status = 'open'
          AND last_span_at IS NOT NULL
          AND last_span_at < {{cutoff:DateTime64(3)}}
        ORDER BY last_span_at ASC
        LIMIT {limit}
        """,
        parameters={"cutoff": _dt_to_ch(cutoff)},
    )
    return [_row_to_trace(r, list(result.column_names)) for r in result.result_rows]


def trace_exists(trace_uuid: UUID) -> bool:
    result = get_client().query(
        "SELECT 1 FROM call_traces FINAL WHERE trace_uuid = {id:UUID} LIMIT 1",
        parameters={"id": trace_uuid},
    )
    return bool(result.result_rows)


def next_batch_seq(trace_uuid: UUID) -> int:
    key = f"trace:batch_seq:{trace_uuid}"
    try:
        return int(_get_redis().incr(key))
    except redis.RedisError as exc:
        logger.warning("Redis batch seq error for {}: {}", trace_uuid, exc)
        return 1


def set_live_turns(trace_uuid: UUID, turns: List[Dict[str, Any]]) -> None:
    ttl = max(1, int(settings.TRACES_LIVE_TURNS_TTL_SECONDS))
    key = f"trace:live:{trace_uuid}"
    try:
        _get_redis().setex(key, ttl, json.dumps(turns, default=str))
    except redis.RedisError as exc:
        logger.warning("Redis live turns error for {}: {}", trace_uuid, exc)


def get_live_turns(trace_uuid: UUID) -> Optional[List[Dict[str, Any]]]:
    key = f"trace:live:{trace_uuid}"
    try:
        raw = _get_redis().get(key)
    except redis.RedisError:
        return None
    if not raw:
        return None
    data = _json_loads(raw)
    return data if isinstance(data, list) else None


def mint_trace_uuid() -> UUID:
    return uuid4()


def ch_store_available() -> bool:
    return clickhouse_enabled()
