"""
Migration: Add silence_hangup_secs to agents.

End live voice sessions after this many seconds without voice activity from either party.
Set to 0 to disable. Default 15 seconds.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add silence_hangup_secs to agents"


def upgrade(db: Session):
    db.execute(text("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS silence_hangup_secs INTEGER NOT NULL DEFAULT 15
    """))
    db.commit()
    print("Added silence_hangup_secs column to agents")


def downgrade(db: Session):
    db.execute(text("""
        ALTER TABLE agents
            DROP COLUMN IF EXISTS silence_hangup_secs
    """))
    db.commit()
    print("Dropped silence_hangup_secs column from agents")
