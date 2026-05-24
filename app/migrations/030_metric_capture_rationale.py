"""
Migration: Add ``metrics.capture_rationale`` opt-in column.

When TRUE the LLM-judge is asked to also return a short free-form rationale
alongside the metric value (stored under
``call_import_evaluation_rows.metric_scores[id].rationale`` and rendered as
a second ``<Name> - LLM Rationale`` column in the call-import CSV export).

Idempotent: skips if the column already exists. Defaults to FALSE so every
existing metric/score keeps its current behavior.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add capture_rationale boolean column to metrics"


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
    if not _table_exists(db, "metrics"):
        print("metrics table does not exist; skipping capture_rationale migration")
        return

    if not _column_exists(db, "metrics", "capture_rationale"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN capture_rationale BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
        )
        print("Added metrics.capture_rationale")

    db.commit()
    print("metrics.capture_rationale column is in place")


def downgrade(db: Session):
    if _table_exists(db, "metrics") and _column_exists(
        db, "metrics", "capture_rationale"
    ):
        db.execute(text("ALTER TABLE metrics DROP COLUMN capture_rationale"))
        db.commit()
