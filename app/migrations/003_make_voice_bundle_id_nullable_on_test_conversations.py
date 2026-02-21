"""
Migration: Make voice_bundle_id nullable on test_agent_conversations

Allows test conversation records to be preserved when their voice bundle is deleted,
with voice_bundle_id set to NULL instead of cascading a delete.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Make voice_bundle_id nullable on test_agent_conversations table"


def upgrade(db: Session):
    """Alter voice_bundle_id column to allow NULL values."""

    result = db.execute(text("""
        SELECT is_nullable
        FROM information_schema.columns
        WHERE table_name = 'test_agent_conversations'
        AND column_name = 'voice_bundle_id'
    """))

    row = result.fetchone()
    if row and row[0] == "YES":
        print("voice_bundle_id is already nullable, skipping...")
        return

    db.execute(text("""
        ALTER TABLE test_agent_conversations
        ALTER COLUMN voice_bundle_id DROP NOT NULL
    """))

    db.commit()
    print("Successfully made voice_bundle_id nullable on test_agent_conversations")


def downgrade(db: Session):
    """Revert voice_bundle_id to NOT NULL (will fail if any NULLs exist)."""
    db.execute(text("""
        ALTER TABLE test_agent_conversations
        ALTER COLUMN voice_bundle_id SET NOT NULL
    """))
    db.commit()
