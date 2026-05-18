"""
Migration: Allow naming a call-import evaluation run.

Adds an optional ``name`` column on ``call_import_evaluations`` so each
run shows up in the UI under a user-chosen label (e.g. "March QA pass")
instead of an opaque UUID prefix. Idempotent.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add optional name column to call_import_evaluations"


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
        text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
        ),
        {"t": table},
    ).first()
    return row is not None


def upgrade(db: Session):
    if _table_exists(db, "call_import_evaluations") and not _column_exists(
        db, "call_import_evaluations", "name"
    ):
        db.execute(
            text(
                "ALTER TABLE call_import_evaluations "
                "ADD COLUMN name VARCHAR(255) NULL"
            )
        )
        print("Added call_import_evaluations.name")
    db.commit()
    print("call_import_evaluations.name is in place")


def downgrade(db: Session):
    db.execute(
        text("ALTER TABLE call_import_evaluations DROP COLUMN IF EXISTS name")
    )
    db.commit()
