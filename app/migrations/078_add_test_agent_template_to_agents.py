"""
Migration: Add test_agent_template JSON column to agents.

Stores structured test agent prompt sections and first-message configuration.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add test_agent_template to agents"


def upgrade(db: Session):
    db.execute(text("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS test_agent_template JSON
    """))
    db.commit()
    print("Added test_agent_template column to agents")


def downgrade(db: Session):
    db.execute(text("""
        ALTER TABLE agents
            DROP COLUMN IF EXISTS test_agent_template
    """))
    db.commit()
    print("Dropped test_agent_template column from agents")
