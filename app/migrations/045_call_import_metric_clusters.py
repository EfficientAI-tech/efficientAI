"""
Migration: Cached per-metric failure clusters on call_import_evaluations.

Adds ``metric_clusters jsonb`` for internal diagnostics clustering
(unsupervised buckets per flagged quality metric + gap labels).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add metric_clusters jsonb column on call_import_evaluations for "
    "internal per-metric failure clustering."
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
    if _column_exists(db, "call_import_evaluations", "metric_clusters"):
        print("call_import_evaluations.metric_clusters already exists, skipping...")
        return

    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluations
            ADD COLUMN metric_clusters JSONB NULL
            """
        )
    )
    print("Added call_import_evaluations.metric_clusters (nullable jsonb)")


def downgrade(db: Session):
    if not _column_exists(db, "call_import_evaluations", "metric_clusters"):
        print("call_import_evaluations.metric_clusters missing, skipping...")
        return
    db.execute(
        text("ALTER TABLE call_import_evaluations DROP COLUMN metric_clusters")
    )
    print("Dropped call_import_evaluations.metric_clusters")
