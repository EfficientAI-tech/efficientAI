"""
Migration: Add optional endpoint_url to aiproviders for Azure OpenAI.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add aiproviders.endpoint_url for Azure OpenAI resource endpoints"


def _column_exists(db: Session, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'aiproviders'
              AND column_name = :column_name
            """
        ),
        {"column_name": column_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _column_exists(db, "endpoint_url"):
        db.execute(
            text(
                """
                ALTER TABLE aiproviders
                ADD COLUMN endpoint_url VARCHAR
                """
            )
        )

    # Backfill: users who stored the Azure URL in the Name field.
    db.execute(
        text(
            """
            UPDATE aiproviders
            SET endpoint_url = TRIM(name)
            WHERE LOWER(provider) = 'azure'
              AND endpoint_url IS NULL
              AND name IS NOT NULL
              AND (
                name ILIKE 'http://%'
                OR name ILIKE 'https://%'
              )
            """
        )
    )

    db.commit()
    print("Added endpoint_url column to aiproviders (with Azure URL backfill)")


def downgrade(db: Session):
    db.execute(text("ALTER TABLE aiproviders DROP COLUMN IF EXISTS endpoint_url"))
    db.commit()
