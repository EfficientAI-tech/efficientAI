"""
Migration: Add metric_ids JSON column to evaluators table.

Custom Prompt evaluators previously stored a free-text agent prompt in
``custom_prompt``. They now (additionally) carry an explicit list of metric
UUIDs the evaluator should score against. The column is nullable so existing
rows (both standard and legacy custom_prompt evaluators) keep working.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add metric_ids JSON column to evaluators"


def _table_exists(db: Session, table_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    )
    return bool(result.scalar())


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = :column_name
            )
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


def upgrade(db: Session):
    if not _table_exists(db, "evaluators"):
        db.commit()
        return

    if not _column_exists(db, "evaluators", "metric_ids"):
        db.execute(text("ALTER TABLE evaluators ADD COLUMN metric_ids JSON"))

    db.commit()


def downgrade(db: Session):
    if _table_exists(db, "evaluators") and _column_exists(db, "evaluators", "metric_ids"):
        db.execute(text("ALTER TABLE evaluators DROP COLUMN metric_ids"))
    db.commit()
