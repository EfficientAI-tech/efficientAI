"""Cache numeric period-over-period metric deltas on the evaluation row."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Cached period deltas for visualization baseline comparisons"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluations
                ADD COLUMN IF NOT EXISTS cached_period_deltas JSONB
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluations
                DROP COLUMN IF EXISTS cached_period_deltas
            """
        )
    )
    db.commit()
