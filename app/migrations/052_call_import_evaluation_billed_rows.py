"""
Migration: Flexprice billing watermark on call_import_evaluations.

Adds ``billed_completed_rows`` so evaluation billing can emit one
``call_import.evaluation_completed`` event per pass with a delta
``quantity`` (newly completed rows since the last pass).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add billed_completed_rows on call_import_evaluations for pass-level "
    "delta usage metering."
)


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
    if _column_exists(db, "call_import_evaluations", "billed_completed_rows"):
        print(
            "call_import_evaluations.billed_completed_rows already exists, skipping..."
        )
        return

    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluations
            ADD COLUMN billed_completed_rows INTEGER NOT NULL DEFAULT 0
            """
        )
    )
    print("Added call_import_evaluations.billed_completed_rows (integer, default 0)")


def downgrade(db: Session):
    if not _column_exists(db, "call_import_evaluations", "billed_completed_rows"):
        print("call_import_evaluations.billed_completed_rows missing, skipping...")
        return
    db.execute(
        text(
            "ALTER TABLE call_import_evaluations DROP COLUMN billed_completed_rows"
        )
    )
    print("Dropped call_import_evaluations.billed_completed_rows")
