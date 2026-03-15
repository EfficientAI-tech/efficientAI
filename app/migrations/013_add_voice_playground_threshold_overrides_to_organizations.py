"""
Migration: Add organization-level Voice Playground threshold overrides.

Stores per-organization defaults for metric zone thresholds used in report legends/bar colors.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add voice_playground_threshold_overrides JSON column to organizations"


def upgrade(db: Session):
    result = db.execute(
        text(
            """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'organizations'
        AND column_name = 'voice_playground_threshold_overrides'
        """
        )
    )

    if result.fetchone() is not None:
        print("Column voice_playground_threshold_overrides already exists on organizations, skipping...")
        return

    db.execute(
        text(
            """
        ALTER TABLE organizations
        ADD COLUMN voice_playground_threshold_overrides JSON
        """
        )
    )

    db.commit()
    print("Added voice_playground_threshold_overrides column to organizations")


def downgrade(db: Session):
    db.execute(text("ALTER TABLE organizations DROP COLUMN IF EXISTS voice_playground_threshold_overrides"))
    db.commit()
