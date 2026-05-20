"""
Migration: Optional ``example`` text on metric rows.

Adds:
  * ``metrics.example`` (TEXT, NULL) - a free-form illustrative example
    used to sharpen the LLM judge's rubric. Today this is consumed by
    child sub-labels of a categorization parent metric (so each label
    can carry "what does this look like in a transcript?" text alongside
    the rubric in ``description``), but the column lives on every
    Metric row for forward-compat: a standalone metric could later
    surface its own example without another migration.

Idempotent: checks for prior existence before applying.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add optional example column to metrics so categorization labels "
    "can carry an illustrative example alongside their definition"
)


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


def upgrade(db: Session):
    if not _column_exists(db, "metrics", "example"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN example TEXT NULL
                """
            )
        )
        print("Added metrics.example")
    else:
        print("metrics.example already exists, skipping...")

    db.commit()
    print("metrics.example column is in place")


def downgrade(db: Session):
    db.execute(text("ALTER TABLE metrics DROP COLUMN IF EXISTS example"))
    db.commit()
