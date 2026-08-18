"""
Migration: add trace_id on call_recordings.

Links OpenTelemetry traces to observability call records.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add trace_id column and index to call_recordings"


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _column_exists(db, "call_recordings", "trace_id"):
        db.execute(
            text(
                """
                ALTER TABLE call_recordings
                ADD COLUMN trace_id VARCHAR(64) NULL
                """
            )
        )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_recordings_trace_id
            ON call_recordings (trace_id)
            """
        )
    )
    db.commit()
    print("Added call_recordings.trace_id")


def downgrade(db: Session):
    db.execute(text("DROP INDEX IF EXISTS ix_call_recordings_trace_id"))
    db.execute(text("ALTER TABLE call_recordings DROP COLUMN IF EXISTS trace_id"))
    db.commit()
