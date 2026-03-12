"""
Migration: Add optional agent_id link to scenarios table.

Allows scenarios to be loosely associated with agents.
If an agent is deleted, scenario.agent_id is set to NULL.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add nullable agent_id to scenarios with ON DELETE SET NULL"


def upgrade(db: Session):
    result = db.execute(
        text(
            """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'scenarios'
        AND column_name = 'agent_id'
        """
        )
    )

    if result.fetchone() is not None:
        print("Column agent_id already exists on scenarios, skipping...")
        return

    db.execute(
        text(
            """
        ALTER TABLE scenarios
        ADD COLUMN agent_id UUID REFERENCES agents(id) ON DELETE SET NULL
        """
        )
    )

    db.execute(
        text(
            """
        CREATE INDEX IF NOT EXISTS ix_scenarios_agent_id
        ON scenarios(agent_id)
        """
        )
    )

    db.commit()
    print("Added agent_id column to scenarios")


def downgrade(db: Session):
    db.execute(text("ALTER TABLE scenarios DROP COLUMN IF EXISTS agent_id"))
    db.commit()
