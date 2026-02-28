"""
Migration: Add custom_tts_voices table for Voice Playground custom voices.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add custom_tts_voices table for provider-specific custom voice IDs"


def upgrade(db: Session):
    result = db.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_name = 'custom_tts_voices'
    """))
    if result.fetchone() is None:
        db.execute(text("""
            CREATE TABLE custom_tts_voices (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                provider VARCHAR(100) NOT NULL,
                voice_id VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                gender VARCHAR(50),
                accent VARCHAR(100),
                description TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_custom_tts_voices_organization_id
            ON custom_tts_voices(organization_id)
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_custom_tts_voices_provider
            ON custom_tts_voices(provider)
        """))
        db.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_custom_tts_voice_org_provider_voice_id
            ON custom_tts_voices(organization_id, provider, voice_id)
        """))
        print("Created custom_tts_voices table")
    else:
        print("custom_tts_voices table already exists, skipping...")

    db.commit()
    print("Successfully completed migration 007")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS custom_tts_voices"))
    db.commit()
