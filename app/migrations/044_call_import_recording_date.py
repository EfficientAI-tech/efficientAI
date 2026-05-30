"""Migration: Add date-only recording dates to call import rows."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add call_import_rows.recording_date date column."


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _column_exists(db, "call_import_rows", "recording_date"):
        db.execute(text("ALTER TABLE call_import_rows ADD COLUMN recording_date DATE"))
        db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_call_import_rows_recording_date "
                "ON call_import_rows (recording_date)"
            )
        )
        print("Added call_import_rows.recording_date")
    else:
        print("call_import_rows.recording_date already exists, skipping")


def downgrade(db: Session):
    if _column_exists(db, "call_import_rows", "recording_date"):
        db.execute(text("DROP INDEX IF EXISTS ix_call_import_rows_recording_date"))
        db.execute(text("ALTER TABLE call_import_rows DROP COLUMN recording_date"))
        print("Dropped call_import_rows.recording_date")
    else:
        print("call_import_rows.recording_date does not exist, skipping")
