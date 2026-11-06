"""Cached metric aggregates for evaluation visualizations."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Cache live metric aggregates on call_import_evaluations"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluations
                ADD COLUMN IF NOT EXISTS cached_metric_aggregates JSONB,
                ADD COLUMN IF NOT EXISTS cached_metric_aggregates_at_count INTEGER
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluations
                DROP COLUMN IF EXISTS cached_metric_aggregates_at_count,
                DROP COLUMN IF EXISTS cached_metric_aggregates
            """
        )
    )
    db.commit()
