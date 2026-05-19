"""
Migration: Add ``call_imports.sheet_name`` VARCHAR column.

Identifies which Excel worksheet a call-import batch came from when the
uploader picked a multi-sheet ``.xlsx``/``.xlsm`` workbook. ``NULL`` for
CSV uploads (and for any pre-Excel-support batches), since CSV files
have no notion of sheets.

Idempotent: re-running is a no-op once the column exists.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add sheet_name VARCHAR column to call_imports"


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
        db, "call_imports", "sheet_name"
    ):
        db.execute(
            text(
                """
                ALTER TABLE call_imports
                ADD COLUMN sheet_name VARCHAR(255) NULL
                """
            )
        )
        print("Added call_imports.sheet_name")
    db.commit()
    print("call_imports.sheet_name is in place")


def downgrade(db: Session):
    db.execute(
        text("ALTER TABLE call_imports DROP COLUMN IF EXISTS sheet_name")
    )
    db.commit()
