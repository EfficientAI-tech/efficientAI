"""Migration: org-level usage margin multiplier for priced rollups."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add organizations.usage_margin_multiplier for usage cost markup"


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


def upgrade(db: Session):
    if not _column_exists(db, "organizations", "usage_margin_multiplier"):
        db.execute(
            text(
                """
                ALTER TABLE organizations
                ADD COLUMN usage_margin_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.0
                """
            )
        )
        print("Added organizations.usage_margin_multiplier")
    db.commit()


def downgrade(db: Session):
    if _column_exists(db, "organizations", "usage_margin_multiplier"):
        db.execute(
            text("ALTER TABLE organizations DROP COLUMN usage_margin_multiplier")
        )
    db.commit()
