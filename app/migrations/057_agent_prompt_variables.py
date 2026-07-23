"""
Migration: Add prompt_variables JSON column to agents.

Stores per-agent custom prompt placeholder keys (and optional descriptions)
for the test agent prompt composer.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add prompt_variables to agents"


def upgrade(db: Session):
    db.execute(text("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS prompt_variables JSON
    """))
    db.commit()
    print("Added prompt_variables column to agents")


def downgrade(db: Session):
    db.execute(text("""
        ALTER TABLE agents
            DROP COLUMN IF EXISTS prompt_variables
    """))
    db.commit()
    print("Dropped prompt_variables column from agents")
