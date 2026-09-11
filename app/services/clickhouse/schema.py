"""Idempotent ClickHouse DDL for call traces."""

from __future__ import annotations

from loguru import logger

from app.services.clickhouse.client import clickhouse_enabled, get_client

CALL_TRACES_DDL = """
CREATE TABLE IF NOT EXISTS call_traces
(
    trace_uuid UUID,
    organization_id UUID,
    workspace_id UUID,
    evaluator_result_id Nullable(UUID),
    agent_id Nullable(UUID),
    persona_id Nullable(UUID),
    scenario_id Nullable(UUID),
    evaluator_id Nullable(UUID),
    call_recording_id Nullable(UUID),
    call_short_id Nullable(String),
    environment String DEFAULT 'pre_prod',
    provider_platform Nullable(String),
    transport String DEFAULT 'phone',
    tier String DEFAULT 'black_box',
    status String DEFAULT 'open',
    started_at DateTime64(3),
    ended_at Nullable(DateTime64(3)),
    turn_count UInt32 DEFAULT 0,
    response_latency_p50_ms Nullable(Float64),
    response_latency_p90_ms Nullable(Float64),
    response_latency_p95_ms Nullable(Float64),
    component_aggregates Nullable(String),
    failure_flags Nullable(String),
    spans_s3_key Nullable(String),
    spans_storage String DEFAULT 'clickhouse',
    span_count UInt32 DEFAULT 0,
    last_span_at Nullable(DateTime64(3)),
    turns Nullable(String),
    updated_at DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (workspace_id, started_at, trace_uuid)
"""

TRACE_OBSERVATIONS_DDL = """
CREATE TABLE IF NOT EXISTS trace_observations
(
    workspace_id UUID,
    trace_uuid UUID,
    span_id String,
    parent_span_id Nullable(String),
    name String,
    kind Nullable(String),
    start_time_unix_nano UInt64,
    end_time_unix_nano UInt64,
    attributes String,
    events String,
    status_code Nullable(String),
    status_message Nullable(String),
    received_at DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree
ORDER BY (workspace_id, trace_uuid, span_id)
"""


def ensure_schema() -> None:
    if not clickhouse_enabled():
        return
    client = get_client()
    client.command(f"CREATE DATABASE IF NOT EXISTS {client.database}")
    client.command(CALL_TRACES_DDL)
    client.command(TRACE_OBSERVATIONS_DDL)
    logger.info("ClickHouse trace schema ready (database=%s)", client.database)
