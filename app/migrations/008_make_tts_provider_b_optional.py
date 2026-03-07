"""
Migration: Make provider_b/model_b/voices_b optional for single-provider TTS benchmarks.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Make TTS comparison provider_b/model_b/voices_b nullable"


def upgrade(db: Session):
    db.execute(text("""
        ALTER TABLE tts_comparisons
        ALTER COLUMN provider_b DROP NOT NULL
    """))
    db.execute(text("""
        ALTER TABLE tts_comparisons
        ALTER COLUMN model_b DROP NOT NULL
    """))
    db.execute(text("""
        ALTER TABLE tts_comparisons
        ALTER COLUMN voices_b DROP NOT NULL
    """))
    db.commit()
    print("Made provider_b/model_b/voices_b nullable on tts_comparisons")


def downgrade(db: Session):
    db.execute(text("""
        UPDATE tts_comparisons
        SET provider_b = 'openai'
        WHERE provider_b IS NULL
    """))
    db.execute(text("""
        UPDATE tts_comparisons
        SET model_b = 'tts-1'
        WHERE model_b IS NULL
    """))
    db.execute(text("""
        UPDATE tts_comparisons
        SET voices_b = '[]'::jsonb
        WHERE voices_b IS NULL
    """))
    db.execute(text("""
        ALTER TABLE tts_comparisons
        ALTER COLUMN provider_b SET NOT NULL
    """))
    db.execute(text("""
        ALTER TABLE tts_comparisons
        ALTER COLUMN model_b SET NOT NULL
    """))
    db.execute(text("""
        ALTER TABLE tts_comparisons
        ALTER COLUMN voices_b SET NOT NULL
    """))
    db.commit()
