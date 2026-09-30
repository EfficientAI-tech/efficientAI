"""Layout 3: short-lived OTLP ingest staging for worker-side parse."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add synthetic_trace_ingest_staging for deferred OTLP parse"

MIGRATION_SCOPE = "catalog"


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


def _index_exists(db: Session, index_name: str) -> bool:
    result = db.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :name)"),
        {"name": index_name},
    )
    return bool(result.scalar())


def upgrade(db: Session) -> None:
    if not _table_exists(db, "synthetic_trace_ingest_staging"):
        db.execute(
            text(
                """
                CREATE TABLE synthetic_trace_ingest_staging (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL,
                    workspace_id UUID NOT NULL,
                    content_type VARCHAR(128) NOT NULL DEFAULT '',
                    body BYTEA NOT NULL,
                    body_bytes INTEGER NOT NULL DEFAULT 0,
                    header_evaluator_result_id VARCHAR(128),
                    header_agent_id VARCHAR(128),
                    header_call_short_id VARCHAR(32),
                    status VARCHAR(16) NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    accepted_spans INTEGER,
                    synthetic_call_trace_id UUID
                        REFERENCES synthetic_call_traces(id) ON DELETE SET NULL,
                    correlated BOOLEAN,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    processed_at TIMESTAMP WITH TIME ZONE
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_trace_ingest_staging_status_received "
                "ON synthetic_trace_ingest_staging(status, received_at)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_trace_ingest_staging_org_ws "
                "ON synthetic_trace_ingest_staging(organization_id, workspace_id)"
            )
        )

    db.commit()


def downgrade(db: Session) -> None:
    if _index_exists(db, "ix_trace_ingest_staging_org_ws"):
        db.execute(text("DROP INDEX ix_trace_ingest_staging_org_ws"))
    if _index_exists(db, "ix_trace_ingest_staging_status_received"):
        db.execute(text("DROP INDEX ix_trace_ingest_staging_status_received"))
    if _table_exists(db, "synthetic_trace_ingest_staging"):
        db.execute(text("DROP TABLE synthetic_trace_ingest_staging"))
    db.commit()
