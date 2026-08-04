"""
Migration: Add persona prompt, TTS config, and caller behavior fields to personas.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add persona prompt, tts_config, and caller behavior fields"


def upgrade(db: Session):
    db.execute(text("""
        ALTER TABLE personas
            ADD COLUMN IF NOT EXISTS description TEXT,
            ADD COLUMN IF NOT EXISTS tts_config JSON,
            ADD COLUMN IF NOT EXISTS llm_temperature DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS llm_max_tokens INTEGER,
            ADD COLUMN IF NOT EXISTS response_delay_ms INTEGER,
            ADD COLUMN IF NOT EXISTS max_turns INTEGER,
            ADD COLUMN IF NOT EXISTS allow_interruptions BOOLEAN
    """))
    db.commit()
    print("Added persona prompt, tts_config, and caller behavior columns")


def downgrade(db: Session):
    db.execute(text("""
        ALTER TABLE personas
            DROP COLUMN IF EXISTS description,
            DROP COLUMN IF EXISTS tts_config,
            DROP COLUMN IF EXISTS llm_temperature,
            DROP COLUMN IF EXISTS llm_max_tokens,
            DROP COLUMN IF EXISTS response_delay_ms,
            DROP COLUMN IF EXISTS max_turns,
            DROP COLUMN IF EXISTS allow_interruptions
    """))
    db.commit()
    print("Dropped persona prompt, tts_config, and caller behavior columns")
