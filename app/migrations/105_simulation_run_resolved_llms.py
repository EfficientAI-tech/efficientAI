"""Snapshot of the LLMs each side of a simulation run uses."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "simulation_runs.resolved_llms JSON column"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(text("""
            ALTER TABLE simulation_runs
                ADD COLUMN IF NOT EXISTS resolved_llms JSON
            """))
    db.commit()


def downgrade(db: Session):
    db.execute(text("""
            ALTER TABLE simulation_runs
                DROP COLUMN IF EXISTS resolved_llms
            """))
    db.commit()
