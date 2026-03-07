"""
Migration: Add num_runs to tts_comparisons and run_index to tts_samples.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add num_runs column to tts_comparisons and run_index to tts_samples"


def upgrade(db: Session):
    # num_runs on tts_comparisons
    result = db.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tts_comparisons' AND column_name = 'num_runs'
    """))
    if result.fetchone() is None:
        db.execute(text("""
            ALTER TABLE tts_comparisons
            ADD COLUMN num_runs INTEGER NOT NULL DEFAULT 1
        """))
        print("Added num_runs column to tts_comparisons")
    else:
        print("num_runs column already exists, skipping...")

    # run_index on tts_samples
    result = db.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'tts_samples' AND column_name = 'run_index'
    """))
    if result.fetchone() is None:
        db.execute(text("""
            ALTER TABLE tts_samples
            ADD COLUMN run_index INTEGER NOT NULL DEFAULT 0
        """))
        print("Added run_index column to tts_samples")
    else:
        print("run_index column already exists, skipping...")

    db.commit()
    print("Successfully completed migration 004")


def downgrade(db: Session):
    db.execute(text("ALTER TABLE tts_samples DROP COLUMN IF EXISTS run_index"))
    db.execute(text("ALTER TABLE tts_comparisons DROP COLUMN IF EXISTS num_runs"))
    db.commit()
