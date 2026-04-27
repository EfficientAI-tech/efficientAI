"""
Migration: Make call_import_rows.recording_url nullable.

The CSV call-import flow originally required the user to paste a Recording URL
on every row. We now also accept rows with only a CallID and resolve the URL
via Exotel's Calls API at worker time, persisting the resolved URL onto the
row. To support that, recording_url must be nullable.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Make call_import_rows.recording_url nullable for CallID-only imports"


def _column_is_nullable(db: Session, table_name: str, column_name: str) -> bool:
    """Return True iff the column exists and is currently NULLABLE."""
    result = db.execute(
        text(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    row = result.first()
    if row is None:
        return False
    return (row[0] or "").upper() == "YES"


def upgrade(db: Session):
    """Drop the NOT NULL constraint on call_import_rows.recording_url."""

    if _column_is_nullable(db, "call_import_rows", "recording_url"):
        print("call_import_rows.recording_url is already nullable, skipping...")
        return

    db.execute(
        text("ALTER TABLE call_import_rows ALTER COLUMN recording_url DROP NOT NULL")
    )
    db.commit()
    print("Made call_import_rows.recording_url nullable")


def downgrade(db: Session):
    """Re-apply NOT NULL. Will fail if any rows have NULL recording_url."""

    db.execute(
        text("ALTER TABLE call_import_rows ALTER COLUMN recording_url SET NOT NULL")
    )
    db.commit()
