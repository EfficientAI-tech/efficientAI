"""
Migration: Add ``call_imports.custom_column_mapping`` JSONB column.

Lets uploaders define their own named fields (e.g. ``agent_name`` →
CSV header ``Rep Name``) on top of the three system fields
(``external_call_id``, ``transcript``, ``recording_url``). The mapped CSV
cells are preserved per row in ``call_import_rows.raw_columns`` and
surfaced under the uploader-chosen name in the evaluation CSV export.

Idempotent: re-running is a no-op once the column exists.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add custom_column_mapping JSONB column to call_imports"


def _column_exists(db: Session, table: str, column: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table, "column_name": column},
    ).first()
    return row is not None


def _table_exists(db: Session, table: str) -> bool:
    row = db.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": table},
    ).first()
    return row is not None


def upgrade(db: Session):
    if _table_exists(db, "call_imports") and not _column_exists(
        db, "call_imports", "custom_column_mapping"
    ):
        db.execute(
            text(
                """
                ALTER TABLE call_imports
                ADD COLUMN custom_column_mapping JSONB NOT NULL DEFAULT '{}'::jsonb
                """
            )
        )
        print("Added call_imports.custom_column_mapping")
    db.commit()
    print("call_imports.custom_column_mapping is in place")


def downgrade(db: Session):
    db.execute(
        text("ALTER TABLE call_imports DROP COLUMN IF EXISTS custom_column_mapping")
    )
    db.commit()
