"""Per-metric success criteria on simulation runs."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "simulation_runs.metric_success_criteria JSON column"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE simulation_runs
                ADD COLUMN IF NOT EXISTS metric_success_criteria JSON
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE simulation_runs
                DROP COLUMN IF EXISTS metric_success_criteria
            """
        )
    )
    db.commit()
