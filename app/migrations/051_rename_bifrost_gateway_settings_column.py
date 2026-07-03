"""
Migration: Rename legacy organizations.bifrost_gateway_settings column.

For databases that applied an earlier 050 migration before the column was
renamed to llm_gateway_settings.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Rename organizations.bifrost_gateway_settings to llm_gateway_settings"
)


def _column_exists(db: Session, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'organizations'
              AND column_name = :column_name
            """
        ),
        {"column_name": column_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if _column_exists(db, "llm_gateway_settings"):
        print("Column llm_gateway_settings already exists, skipping rename...")
        return

    if not _column_exists(db, "bifrost_gateway_settings"):
        print("Legacy bifrost_gateway_settings column not found, skipping rename...")
        return

    db.execute(
        text(
            """
        ALTER TABLE organizations
        RENAME COLUMN bifrost_gateway_settings TO llm_gateway_settings
        """
        )
    )
    db.commit()
    print(
        "Renamed organizations.bifrost_gateway_settings "
        "to llm_gateway_settings"
    )


def downgrade(db: Session):
    if _column_exists(db, "bifrost_gateway_settings"):
        print("Column bifrost_gateway_settings already exists, skipping rename...")
        return

    if not _column_exists(db, "llm_gateway_settings"):
        print("Column llm_gateway_settings not found, skipping rename...")
        return

    db.execute(
        text(
            """
        ALTER TABLE organizations
        RENAME COLUMN llm_gateway_settings TO bifrost_gateway_settings
        """
        )
    )
    db.commit()
