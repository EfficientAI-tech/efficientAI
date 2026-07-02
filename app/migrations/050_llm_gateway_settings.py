"""
Migration: Add per-organization LLM gateway settings JSON column.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add organizations.llm_gateway_settings JSON for per-org LLM gateway overrides"


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
        print("Column llm_gateway_settings already exists on organizations, skipping...")
        return

    db.execute(
        text(
            """
        ALTER TABLE organizations
        ADD COLUMN llm_gateway_settings JSON
        """
        )
    )

    db.commit()
    print("Added llm_gateway_settings column to organizations")


def downgrade(db: Session):
    db.execute(
        text("ALTER TABLE organizations DROP COLUMN IF EXISTS llm_gateway_settings")
    )
    db.commit()
