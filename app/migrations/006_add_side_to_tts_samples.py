"""
Migration: Add side column to tts_samples to distinguish A/B sides.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add side column (A/B) to tts_samples for same-provider comparisons"


def upgrade(db: Session):
    result = db.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tts_samples' AND column_name = 'side'
    """))
    if result.fetchone() is None:
        db.execute(text("""
            ALTER TABLE tts_samples
            ADD COLUMN side VARCHAR(1) DEFAULT NULL
        """))
        print("Added side column to tts_samples")
    else:
        print("side column already exists, skipping...")

    db.commit()
    print("Successfully completed migration 006")


def downgrade(db: Session):
    db.execute(text("ALTER TABLE tts_samples DROP COLUMN IF EXISTS side"))
    db.commit()
