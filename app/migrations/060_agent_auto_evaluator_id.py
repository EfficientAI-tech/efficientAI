"""
Migration: add observability_auto_evaluator_id to agents.

Allows auto-queueing evaluator runs for observability call_ended ingestion.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add observability_auto_evaluator_id column to agents"


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _column_exists(db, "agents", "observability_auto_evaluator_id"):
        db.execute(
            text(
                """
                ALTER TABLE agents
                ADD COLUMN observability_auto_evaluator_id UUID NULL
                """
            )
        )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_agents_observability_auto_evaluator_id
            ON agents (observability_auto_evaluator_id)
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE agents
            ADD CONSTRAINT fk_agents_observability_auto_evaluator_id
            FOREIGN KEY (observability_auto_evaluator_id)
            REFERENCES evaluators (id)
            ON DELETE SET NULL
            """
        )
    )
    db.commit()
    print("Added agents.observability_auto_evaluator_id")


def downgrade(db: Session):
    db.execute(text("ALTER TABLE agents DROP CONSTRAINT IF EXISTS fk_agents_observability_auto_evaluator_id"))
    db.execute(text("DROP INDEX IF EXISTS ix_agents_observability_auto_evaluator_id"))
    db.execute(text("ALTER TABLE agents DROP COLUMN IF EXISTS observability_auto_evaluator_id"))
    db.commit()
