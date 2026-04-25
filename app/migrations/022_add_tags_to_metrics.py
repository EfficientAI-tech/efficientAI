"""
Migration: Add tags column to metrics table.

Older installations were missing the `tags` JSON column that the SQLAlchemy
`Metric` model expects. Migration 021 added the surface/origin columns but
not `tags`, so this migration backfills it for any database where it is
still absent.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add tags JSON column to metrics"


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
    if not _table_exists(db, "metrics"):
        db.commit()
        return

    if not _column_exists(db, "metrics", "tags"):
        db.execute(text("ALTER TABLE metrics ADD COLUMN tags JSON"))

    db.commit()


def downgrade(db: Session):
    if _table_exists(db, "metrics") and _column_exists(db, "metrics", "tags"):
        db.execute(text("ALTER TABLE metrics DROP COLUMN tags"))
    db.commit()
