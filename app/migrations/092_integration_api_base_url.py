"""
Migration: Add optional api_base_url to integrations for ElevenLabs data residency.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add integrations.api_base_url for ElevenLabs regional API hosts"


def _column_exists(db: Session, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'integrations'
              AND column_name = :column_name
            """
        ),
        {"column_name": column_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _column_exists(db, "api_base_url"):
        db.execute(
            text(
                """
                ALTER TABLE integrations
                ADD COLUMN api_base_url VARCHAR
                """
            )
        )

    db.commit()
    print("Added api_base_url column to integrations")


def downgrade(db: Session):
    db.execute(text("ALTER TABLE integrations DROP COLUMN IF EXISTS api_base_url"))
    db.commit()
