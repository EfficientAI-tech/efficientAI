"""Phase 2 trace scaling: append-only span batches, S3 pointers, list index."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add synthetic_trace_span_batches and trace scaling columns"

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


def _index_exists(db: Session, index_name: str) -> bool:
    result = db.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :name)"),
        {"name": index_name},
    )
    return bool(result.scalar())


def upgrade(db: Session) -> None:
    if not _table_exists(db, "synthetic_trace_span_batches"):
        db.execute(
            text(
                """
                CREATE TABLE synthetic_trace_span_batches (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    synthetic_call_trace_id UUID NOT NULL
                        REFERENCES synthetic_call_traces(id) ON DELETE CASCADE,
                    workspace_id UUID NOT NULL,
                    seq BIGSERIAL NOT NULL,
                    span_count INTEGER NOT NULL DEFAULT 0,
                    spans JSONB NOT NULL DEFAULT '[]'::jsonb,
                    received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_trace_span_batches_trace_seq "
                "ON synthetic_trace_span_batches(synthetic_call_trace_id, seq)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_trace_span_batches_workspace "
                "ON synthetic_trace_span_batches(workspace_id)"
            )
        )

    columns = [
        ("spans_s3_key", "VARCHAR(512)"),
        ("spans_storage", "VARCHAR(16) NOT NULL DEFAULT 'legacy_jsonb'"),
        ("span_count", "INTEGER NOT NULL DEFAULT 0"),
        ("last_span_at", "TIMESTAMP WITH TIME ZONE"),
        ("derive_pending", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ]
    for col_name, col_type in columns:
        if not _column_exists(db, "synthetic_call_traces", col_name):
            db.execute(
                text(f"ALTER TABLE synthetic_call_traces ADD COLUMN {col_name} {col_type}")
            )

    if not _index_exists(db, "ix_synthetic_call_traces_org_ws_started_id"):
        db.execute(
            text(
                "CREATE INDEX ix_synthetic_call_traces_org_ws_started_id "
                "ON synthetic_call_traces(organization_id, workspace_id, started_at DESC, id DESC)"
            )
        )

    db.commit()


def downgrade(db: Session) -> None:
    if _index_exists(db, "ix_synthetic_call_traces_org_ws_started_id"):
        db.execute(text("DROP INDEX ix_synthetic_call_traces_org_ws_started_id"))
    for col in ("derive_pending", "last_span_at", "span_count", "spans_storage", "spans_s3_key"):
        if _column_exists(db, "synthetic_call_traces", col):
            db.execute(text(f"ALTER TABLE synthetic_call_traces DROP COLUMN {col}"))
    if _table_exists(db, "synthetic_trace_span_batches"):
        db.execute(text("DROP TABLE synthetic_trace_span_batches"))
    db.commit()
