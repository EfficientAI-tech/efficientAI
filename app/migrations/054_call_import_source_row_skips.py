"""
Migration: Persist parse-time skip summary on call imports.

Adds ``source_row_skips`` JSON on ``call_imports`` for rows excluded
during CSV/Excel materialization (missing/invalid conversation ID or URL).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add call_imports.source_row_skips for parse-time row skip summary."


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
    if not _column_exists(db, "call_imports", "source_row_skips"):
        db.execute(
            text(
                """
                ALTER TABLE call_imports
                ADD COLUMN source_row_skips JSON NOT NULL DEFAULT '[]'::json
                """
            )
        )


def downgrade(db: Session):
    if _column_exists(db, "call_imports", "source_row_skips"):
        db.execute(text("ALTER TABLE call_imports DROP COLUMN source_row_skips"))
