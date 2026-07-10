"""
Migration: Per-integration LLM gateway routing settings.

Adds ``routing_mode`` and ``gateway_model`` to aiproviders, and
``routing_mode`` to integrations (voice platforms).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add per-credential routing_mode and gateway_model for AI providers "
    "and voice platform integrations."
)


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
    if not _column_exists(db, "aiproviders", "routing_mode"):
        db.execute(
            text(
                """
                ALTER TABLE aiproviders
                ADD COLUMN routing_mode VARCHAR(20) NOT NULL DEFAULT 'inherit'
                """
            )
        )
        print("Added aiproviders.routing_mode (varchar, default 'inherit')")

    if not _column_exists(db, "aiproviders", "gateway_model"):
        db.execute(
            text(
                """
                ALTER TABLE aiproviders
                ADD COLUMN gateway_model VARCHAR(255) NULL
                """
            )
        )
        print("Added aiproviders.gateway_model (varchar, nullable)")

    if not _column_exists(db, "integrations", "routing_mode"):
        db.execute(
            text(
                """
                ALTER TABLE integrations
                ADD COLUMN routing_mode VARCHAR(20) NOT NULL DEFAULT 'inherit'
                """
            )
        )
        print("Added integrations.routing_mode (varchar, default 'inherit')")


def downgrade(db: Session):
    if _column_exists(db, "integrations", "routing_mode"):
        db.execute(text("ALTER TABLE integrations DROP COLUMN routing_mode"))
        print("Dropped integrations.routing_mode")

    if _column_exists(db, "aiproviders", "gateway_model"):
        db.execute(text("ALTER TABLE aiproviders DROP COLUMN gateway_model"))
        print("Dropped aiproviders.gateway_model")

    if _column_exists(db, "aiproviders", "routing_mode"):
        db.execute(text("ALTER TABLE aiproviders DROP COLUMN routing_mode"))
        print("Dropped aiproviders.routing_mode")
