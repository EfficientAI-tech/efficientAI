"""
Migration: Add creator_notes to tts_blind_test_shares.

For standalone blind tests (especially over recordings / uploads), the
provider/voice fields aren't enough context for the creator to remember what
each side actually is. `creator_notes` is a free-form text field that is only
visible to the comparison owner inside the dashboard - it is intentionally
NOT included in the public blind test payload.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add creator_notes column to tts_blind_test_shares"


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


def upgrade(db: Session):
    if not _column_exists(db, "tts_blind_test_shares", "creator_notes"):
        db.execute(
            text(
                """
                ALTER TABLE tts_blind_test_shares
                ADD COLUMN creator_notes TEXT NULL
                """
            )
        )
        print("Added tts_blind_test_shares.creator_notes")
    db.commit()


def downgrade(db: Session):
    db.execute(text("ALTER TABLE tts_blind_test_shares DROP COLUMN IF EXISTS creator_notes"))
    db.commit()
