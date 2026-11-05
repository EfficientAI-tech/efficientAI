"""Widen evaluation_analysis_batches.status so synthesis_completed fits.

The original column was VARCHAR(16). The insights synthesis checkpoint writes
status 'synthesis_completed' (19 characters) and Postgres rejected the insert.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Widen evaluation_analysis_batches.status to VARCHAR(32)"
MIGRATION_SCOPE = "all"


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _table_exists(db, "evaluation_analysis_batches"):
        db.commit()
        return
    db.execute(
        text(
            """
            ALTER TABLE evaluation_analysis_batches
                ALTER COLUMN status TYPE VARCHAR(32)
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "evaluation_analysis_batches"):
        db.commit()
        return
    db.execute(
        text(
            """
            ALTER TABLE evaluation_analysis_batches
                ALTER COLUMN status TYPE VARCHAR(16)
            """
        )
    )
    db.commit()
