"""
Migration: Add eval_stt_provider and eval_stt_model to tts_comparisons.

Allows per-comparison STT provider override for WER/CER evaluation.
When NULL the worker falls back to the org's first Voice Bundle STT config.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add eval_stt_provider and eval_stt_model columns to tts_comparisons"


def upgrade(db: Session):
    existing = db.execute(
        text(
            """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'tts_comparisons'
        AND column_name = 'eval_stt_provider'
        """
        )
    )

    if existing.fetchone() is not None:
        print("Column eval_stt_provider already exists on tts_comparisons, skipping...")
        return

    db.execute(
        text(
            """
        ALTER TABLE tts_comparisons
        ADD COLUMN eval_stt_provider VARCHAR(100),
        ADD COLUMN eval_stt_model VARCHAR(100)
        """
        )
    )

    db.commit()
    print("Added eval_stt_provider and eval_stt_model columns to tts_comparisons")


def downgrade(db: Session):
    db.execute(text("ALTER TABLE tts_comparisons DROP COLUMN IF EXISTS eval_stt_provider"))
    db.execute(text("ALTER TABLE tts_comparisons DROP COLUMN IF EXISTS eval_stt_model"))
    db.commit()
