"""
Migration: Add provider_prompt columns to agents table.

Stores the system prompt fetched from the voice provider (Vapi, Retell,
ElevenLabs) so the optimization pipeline can use the actual production
prompt as the seed rather than the local description field.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add provider_prompt and provider_prompt_synced_at to agents"


def upgrade(db: Session):
    db.execute(text("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS provider_prompt TEXT,
            ADD COLUMN IF NOT EXISTS provider_prompt_synced_at TIMESTAMPTZ
    """))
    db.commit()
    print("Added provider_prompt and provider_prompt_synced_at columns to agents")


def downgrade(db: Session):
    db.execute(text("""
        ALTER TABLE agents
            DROP COLUMN IF EXISTS provider_prompt,
            DROP COLUMN IF EXISTS provider_prompt_synced_at
    """))
    db.commit()
    print("Dropped provider_prompt columns from agents")
