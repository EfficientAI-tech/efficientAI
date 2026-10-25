"""Failure clusters and prompt suggestions for simulation runs."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "simulation_runs.metric_clusters and prompt_improvements JSON columns"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(text("""
            ALTER TABLE simulation_runs
                ADD COLUMN IF NOT EXISTS metric_clusters JSON,
                ADD COLUMN IF NOT EXISTS prompt_improvements JSON
            """))
    db.commit()


def downgrade(db: Session):
    db.execute(text("""
            ALTER TABLE simulation_runs
                DROP COLUMN IF EXISTS metric_clusters,
                DROP COLUMN IF EXISTS prompt_improvements
            """))
    db.commit()
