"""
Migration: Add ttfb_ms (Time-To-First-Byte) column to tts_samples table.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add ttfb_ms column to tts_samples for TTFB latency tracking"


def upgrade(db: Session):
    db.execute(text("""
        ALTER TABLE tts_samples
        ADD COLUMN IF NOT EXISTS ttfb_ms FLOAT
    """))
    db.commit()
    print("Added ttfb_ms column to tts_samples")


def downgrade(db: Session):
    db.execute(text("""
        ALTER TABLE tts_samples
        DROP COLUMN IF EXISTS ttfb_ms
    """))
    db.commit()
