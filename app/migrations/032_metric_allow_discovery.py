"""
Migration: Allow-discovery flag on parent metrics.

Adds:
  * ``metrics.allow_discovery`` (BOOLEAN, NOT NULL, default FALSE) - when
    true on a ``multi_label`` parent metric, the LLM is invited during
    evaluation to emit additional candidate sub-labels beyond the
    user-defined children. Those candidates surface in a "Discovered
    labels" panel where the user can manually promote them into real
    child Metric rows.

Idempotent: checks for prior existence before applying.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add allow_discovery flag to metrics so multi_label parents can opt "
    "into LLM-driven sub-label discovery during call import evaluation"
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
    if not _column_exists(db, "metrics", "allow_discovery"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN allow_discovery BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
        )
        print("Added metrics.allow_discovery")
    else:
        print("metrics.allow_discovery already exists, skipping...")

    db.commit()
    print("allow_discovery flag is in place")


def downgrade(db: Session):
    db.execute(
        text("ALTER TABLE metrics DROP COLUMN IF EXISTS allow_discovery")
    )
    db.commit()
