"""
Migration: Revamp personas table for TTS provider-based voice selection.

Replaces generic speech attributes (language, accent, background_noise) with
TTS provider-tied voice identity fields (tts_provider, tts_voice_id,
tts_voice_name, is_custom).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Revamp personas: add TTS voice fields, drop language/accent/background_noise"


def upgrade(db: Session):
    db.execute(text("""
        ALTER TABLE personas
            ADD COLUMN IF NOT EXISTS tts_provider VARCHAR(100),
            ADD COLUMN IF NOT EXISTS tts_voice_id VARCHAR(255),
            ADD COLUMN IF NOT EXISTS tts_voice_name VARCHAR(255),
            ADD COLUMN IF NOT EXISTS is_custom BOOLEAN DEFAULT FALSE,
            DROP COLUMN IF EXISTS language,
            DROP COLUMN IF EXISTS accent,
            DROP COLUMN IF EXISTS background_noise
    """))
    db.commit()
    print("Revamped personas table: added TTS voice fields, dropped language/accent/background_noise")


def downgrade(db: Session):
    db.execute(text("""
        ALTER TABLE personas
            ADD COLUMN IF NOT EXISTS language VARCHAR(50) DEFAULT 'en',
            ADD COLUMN IF NOT EXISTS accent VARCHAR(50) DEFAULT 'american',
            ADD COLUMN IF NOT EXISTS background_noise VARCHAR(50) DEFAULT 'none',
            DROP COLUMN IF EXISTS tts_provider,
            DROP COLUMN IF EXISTS tts_voice_id,
            DROP COLUMN IF EXISTS tts_voice_name,
            DROP COLUMN IF EXISTS is_custom
    """))
    db.commit()
    print("Reverted personas table: restored language/accent/background_noise, dropped TTS voice fields")
