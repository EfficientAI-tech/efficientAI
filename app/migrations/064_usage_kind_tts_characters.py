"""Migration: TTS usage_kind + tts_characters metric."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add tts_characters to llm_usage_daily and usage_pending_buffer for TTS usage"


def _column_exists(db: Session, table: str, column: str) -> bool:
    return (
        db.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = :column_name
                """
            ),
            {"table_name": table, "column_name": column},
        ).first()
        is not None
    )


def _table_exists(db: Session, table: str) -> bool:
    return (
        db.execute(
            text(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_name = :table_name
                """
            ),
            {"table_name": table},
        ).first()
        is not None
    )


def upgrade(db: Session):
    if _table_exists(db, "llm_usage_daily") and not _column_exists(
        db, "llm_usage_daily", "tts_characters"
    ):
        db.execute(
            text(
                """
                ALTER TABLE llm_usage_daily
                ADD COLUMN tts_characters BIGINT NOT NULL DEFAULT 0
                """
            )
        )
        print("Added tts_characters to llm_usage_daily")

    if _table_exists(db, "usage_pending_buffer") and not _column_exists(
        db, "usage_pending_buffer", "tts_characters"
    ):
        db.execute(
            text(
                """
                ALTER TABLE usage_pending_buffer
                ADD COLUMN tts_characters BIGINT NOT NULL DEFAULT 0
                """
            )
        )
        print("Added tts_characters to usage_pending_buffer")

    db.commit()


def downgrade(db: Session):
    if _column_exists(db, "llm_usage_daily", "tts_characters"):
        db.execute(text("ALTER TABLE llm_usage_daily DROP COLUMN tts_characters"))
    if _column_exists(db, "usage_pending_buffer", "tts_characters"):
        db.execute(text("ALTER TABLE usage_pending_buffer DROP COLUMN tts_characters"))
    db.commit()
