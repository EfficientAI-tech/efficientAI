"""
Migration: Add dual-flow support to TTS comparisons / samples.

Adds:
  - tts_comparisons.mode (string, default 'benchmark') – distinguishes the
    new "blind_test_only" flow (no TTS generation) from the existing TTS
    benchmark flow.
  - tts_samples.source_type (string, default 'tts') – per-sample source kind:
    'tts' (provider-generated), 'recording' (re-uses a CallImportRow's
    recording_s3_key), or 'upload' (user-supplied audio file).
  - tts_samples.source_ref_id (uuid, nullable) – references call_import_rows.id
    when source_type == 'recording'.

Loosens NOT NULL on:
  - tts_comparisons.provider_a / model_a / voices_a
  - tts_samples.provider / model / voice_id
…so a side / sample can be a recording or upload with no TTS provider.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Voice Playground dual flow: comparison.mode + sample.source_type/source_ref_id, nullable providers"


def _column_exists(db: Session, table: str, column: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table, "column_name": column},
    ).first()
    return row is not None


def _column_is_nullable(db: Session, table: str, column: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table, "column_name": column},
    ).first()
    if row is None:
        return False
    return (row[0] or "").upper() == "YES"


def upgrade(db: Session):
    if not _column_exists(db, "tts_comparisons", "mode"):
        db.execute(
            text(
                """
                ALTER TABLE tts_comparisons
                ADD COLUMN mode VARCHAR(32) NOT NULL DEFAULT 'benchmark'
                """
            )
        )
        print("Added tts_comparisons.mode")

    if not _column_exists(db, "tts_samples", "source_type"):
        db.execute(
            text(
                """
                ALTER TABLE tts_samples
                ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'tts'
                """
            )
        )
        print("Added tts_samples.source_type")

    if not _column_exists(db, "tts_samples", "source_ref_id"):
        db.execute(
            text(
                """
                ALTER TABLE tts_samples
                ADD COLUMN source_ref_id UUID NULL
                """
            )
        )
        print("Added tts_samples.source_ref_id")

    for col in ("provider_a", "model_a", "voices_a"):
        if not _column_is_nullable(db, "tts_comparisons", col):
            db.execute(
                text(f"ALTER TABLE tts_comparisons ALTER COLUMN {col} DROP NOT NULL")
            )
            print(f"Made tts_comparisons.{col} nullable")

    for col in ("provider", "model", "voice_id"):
        if not _column_is_nullable(db, "tts_samples", col):
            db.execute(
                text(f"ALTER TABLE tts_samples ALTER COLUMN {col} DROP NOT NULL")
            )
            print(f"Made tts_samples.{col} nullable")

    db.commit()


def downgrade(db: Session):
    db.execute(text("ALTER TABLE tts_samples DROP COLUMN IF EXISTS source_ref_id"))
    db.execute(text("ALTER TABLE tts_samples DROP COLUMN IF EXISTS source_type"))
    db.execute(text("ALTER TABLE tts_comparisons DROP COLUMN IF EXISTS mode"))
    db.commit()
