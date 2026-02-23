"""
Migration: Add simulation_id to tts_comparisons for human-readable tracking.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add simulation_id column (unique 6-digit ID) to tts_comparisons"


def upgrade(db: Session):
    result = db.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tts_comparisons' AND column_name = 'simulation_id'
    """))
    if result.fetchone() is None:
        db.execute(text("""
            ALTER TABLE tts_comparisons
            ADD COLUMN simulation_id VARCHAR(6) UNIQUE
        """))
        db.execute(text("""
            CREATE INDEX ix_tts_comparisons_simulation_id ON tts_comparisons (simulation_id)
        """))
        print("Added simulation_id column to tts_comparisons")
    else:
        print("simulation_id column already exists, skipping...")

    db.commit()
    print("Successfully completed migration 005")


def downgrade(db: Session):
    db.execute(text("DROP INDEX IF EXISTS ix_tts_comparisons_simulation_id"))
    db.execute(text("ALTER TABLE tts_comparisons DROP COLUMN IF EXISTS simulation_id"))
    db.commit()
