"""
Migration: unique persona+scenario pairs per evaluator suite child row.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add unique index on evaluators (suite_id, persona_id, scenario_id)"


def upgrade(db: Session):
    db.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_evaluator_suite_persona_scenario
        ON evaluators (suite_id, persona_id, scenario_id)
        WHERE suite_id IS NOT NULL
          AND persona_id IS NOT NULL
          AND scenario_id IS NOT NULL
    """))
    db.commit()
    print("Added uq_evaluator_suite_persona_scenario index on evaluators")


def downgrade(db: Session):
    db.execute(text("""
        DROP INDEX IF EXISTS uq_evaluator_suite_persona_scenario
    """))
    db.commit()
    print("Dropped uq_evaluator_suite_persona_scenario index on evaluators")
