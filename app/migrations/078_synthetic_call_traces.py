"""Add synthetic call trace tables for Pipecat phone + OTLP observability."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add synthetic_call_traces, payload tables, and evaluator_results link"


def _table_exists(db: Session, table_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    )
    return bool(result.scalar())


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = :column_name
            )
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


def upgrade(db: Session) -> None:
    if not _table_exists(db, "synthetic_call_traces"):
        db.execute(
            text(
                """
                CREATE TABLE synthetic_call_traces (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    workspace_id UUID NOT NULL REFERENCES workspaces(id),
                    evaluator_result_id UUID REFERENCES evaluator_results(id) ON DELETE SET NULL,
                    agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
                    persona_id UUID REFERENCES personas(id) ON DELETE SET NULL,
                    scenario_id UUID REFERENCES scenarios(id) ON DELETE SET NULL,
                    evaluator_id UUID REFERENCES evaluators(id) ON DELETE SET NULL,
                    call_recording_id UUID REFERENCES call_recordings(id) ON DELETE SET NULL,
                    call_short_id VARCHAR(6),
                    environment VARCHAR(32) NOT NULL DEFAULT 'pre_prod',
                    provider_platform VARCHAR(64),
                    transport VARCHAR(32) NOT NULL DEFAULT 'phone',
                    tier VARCHAR(32) NOT NULL DEFAULT 'black_box',
                    status VARCHAR(32) NOT NULL DEFAULT 'open',
                    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    ended_at TIMESTAMP WITH TIME ZONE,
                    turn_count INTEGER NOT NULL DEFAULT 0,
                    response_latency_p50_ms DOUBLE PRECISION,
                    response_latency_p90_ms DOUBLE PRECISION,
                    response_latency_p95_ms DOUBLE PRECISION,
                    component_aggregates JSONB,
                    failure_flags JSONB,
                    trace_version INTEGER NOT NULL DEFAULT 1,
                    shard_id VARCHAR(64),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_synthetic_call_traces_org_agent_started "
                "ON synthetic_call_traces(organization_id, agent_id, started_at)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_synthetic_call_traces_evaluator_result "
                "ON synthetic_call_traces(evaluator_result_id)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_synthetic_call_traces_call_short_id "
                "ON synthetic_call_traces(call_short_id)"
            )
        )

    if not _table_exists(db, "synthetic_trace_payloads"):
        db.execute(
            text(
                """
                CREATE TABLE synthetic_trace_payloads (
                    synthetic_call_trace_id UUID PRIMARY KEY
                        REFERENCES synthetic_call_traces(id) ON DELETE CASCADE,
                    workspace_id UUID NOT NULL,
                    turns JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_synthetic_trace_payloads_workspace "
                "ON synthetic_trace_payloads(workspace_id)"
            )
        )

    if not _table_exists(db, "synthetic_trace_otel_payloads"):
        db.execute(
            text(
                """
                CREATE TABLE synthetic_trace_otel_payloads (
                    synthetic_call_trace_id UUID PRIMARY KEY
                        REFERENCES synthetic_call_traces(id) ON DELETE CASCADE,
                    workspace_id UUID NOT NULL,
                    spans JSONB NOT NULL DEFAULT '[]'::jsonb,
                    trace_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_synthetic_trace_otel_payloads_workspace "
                "ON synthetic_trace_otel_payloads(workspace_id)"
            )
        )

    if not _column_exists(db, "evaluator_results", "synthetic_call_trace_id"):
        db.execute(
            text(
                """
                ALTER TABLE evaluator_results
                ADD COLUMN synthetic_call_trace_id UUID
                    REFERENCES synthetic_call_traces(id) ON DELETE SET NULL
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_evaluator_results_synthetic_call_trace_id "
                "ON evaluator_results(synthetic_call_trace_id)"
            )
        )

    db.commit()


def downgrade(db: Session) -> None:
    if _column_exists(db, "evaluator_results", "synthetic_call_trace_id"):
        db.execute(text("ALTER TABLE evaluator_results DROP COLUMN synthetic_call_trace_id"))
    for table in (
        "synthetic_trace_otel_payloads",
        "synthetic_trace_payloads",
        "synthetic_call_traces",
    ):
        if _table_exists(db, table):
            db.execute(text(f"DROP TABLE {table}"))
    db.commit()
