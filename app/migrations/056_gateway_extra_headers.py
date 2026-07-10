"""
Migration: Arbitrary per-credential gateway HTTP headers.

Adds ``gateway_extra_headers`` JSON on aiproviders for custom headers sent
with every gateway-routed LiteLLM call.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add gateway_extra_headers JSON on aiproviders for custom gateway headers."


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _column_exists(db, "aiproviders", "gateway_extra_headers"):
        db.execute(
            text(
                """
                ALTER TABLE aiproviders
                ADD COLUMN gateway_extra_headers JSON NULL
                """
            )
        )
        print("Added aiproviders.gateway_extra_headers (json, nullable)")


def downgrade(db: Session):
    if _column_exists(db, "aiproviders", "gateway_extra_headers"):
        db.execute(text("ALTER TABLE aiproviders DROP COLUMN gateway_extra_headers"))
        print("Dropped aiproviders.gateway_extra_headers")
