"""
Migration: Add per-credential gateway_type (inherit | bifrost | litellm_proxy) to aiproviders.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add aiproviders.gateway_type for per-credential Bifrost / LiteLLM Proxy selection"


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
    if not _column_exists(db, "gateway_type"):
        db.execute(
            text(
                """
                ALTER TABLE aiproviders
                ADD COLUMN gateway_type VARCHAR(20) NOT NULL DEFAULT 'inherit'
                """
            )
        )

    db.commit()
    print("Added gateway_type column to aiproviders")


def downgrade(db: Session):
    db.execute(text("ALTER TABLE aiproviders DROP COLUMN IF EXISTS gateway_type"))
    db.commit()
