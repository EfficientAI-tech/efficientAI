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
    updated_at DateTime64(3) DEFAULT now64(3),
    INDEX idx_trace_uuid trace_uuid TYPE bloom_filter GRANULARITY 4,
    INDEX idx_call_short_id call_short_id TYPE bloom_filter GRANULARITY 4,
    INDEX idx_evaluator_result evaluator_result_id TYPE bloom_filter GRANULARITY 4
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(started_at)
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
ENGINE = ReplacingMergeTree(received_at)
PARTITION BY toYYYYMM(received_at)
ORDER BY (workspace_id, trace_uuid, span_id)
"""

_TRACE_INDEX_ALTER_STATEMENTS = [
    "ALTER TABLE call_traces ADD INDEX IF NOT EXISTS idx_trace_uuid trace_uuid TYPE bloom_filter GRANULARITY 4",
    "ALTER TABLE call_traces ADD INDEX IF NOT EXISTS idx_call_short_id call_short_id TYPE bloom_filter GRANULARITY 4",
    "ALTER TABLE call_traces ADD INDEX IF NOT EXISTS idx_evaluator_result evaluator_result_id TYPE bloom_filter GRANULARITY 4",
]

_TRACE_OBSERVATIONS_LEGACY_TABLE = "trace_observations__legacy_mergetree"


def _table_engine(client, table_name: str) -> str | None:
    result = client.query(
        "SELECT engine FROM system.tables "
        "WHERE database = {db:String} AND name = {name:String}",
        parameters={"db": client.database, "name": table_name},
    )
    if not result.result_rows:
        return None
    return str(result.result_rows[0][0])


def _trace_observations_ddl(table_name: str) -> str:
    return TRACE_OBSERVATIONS_DDL.replace(
        "CREATE TABLE IF NOT EXISTS trace_observations",
        f"CREATE TABLE {table_name}",
    )


def _migrate_trace_observations_engine(client) -> None:
    engine = _table_engine(client, "trace_observations")
    if engine is None or engine == "ReplacingMergeTree":
        return
    if engine != "MergeTree":
        logger.warning(
            "trace_observations uses unexpected engine {}, skipping migration",
            engine,
        )
        return

    logger.info("Migrating trace_observations from MergeTree to ReplacingMergeTree")
    client.command(
        f"RENAME TABLE trace_observations TO {_TRACE_OBSERVATIONS_LEGACY_TABLE}"
    )
    try:
        client.command(_trace_observations_ddl("trace_observations"))
        client.command(
            f"INSERT INTO trace_observations SELECT * FROM {_TRACE_OBSERVATIONS_LEGACY_TABLE}"
        )
        client.command(f"DROP TABLE {_TRACE_OBSERVATIONS_LEGACY_TABLE}")
    except Exception:
        client.command(f"DROP TABLE IF EXISTS trace_observations")
        client.command(
            f"RENAME TABLE {_TRACE_OBSERVATIONS_LEGACY_TABLE} TO trace_observations"
        )
        raise
    logger.info("trace_observations engine migration complete")


def ensure_schema() -> None:
    if not clickhouse_enabled():
        return
    client = get_client()
    client.command(f"CREATE DATABASE IF NOT EXISTS {client.database}")
    client.command(CALL_TRACES_DDL)
    client.command(TRACE_OBSERVATIONS_DDL)
    _migrate_trace_observations_engine(client)
    for stmt in _TRACE_INDEX_ALTER_STATEMENTS:
        try:
            client.command(stmt)
        except Exception as exc:
            logger.debug("ClickHouse index alter skipped: {}", exc)
    logger.info("ClickHouse trace schema ready (database=%s)", client.database)
