"""
Migration: Bifrost gateway interface and per-credential base URL overrides.

Adds ``gateway_interface`` and ``gateway_base_url`` to aiproviders for
native OpenAI-compatible Bifrost routing vs the /litellm shim.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add gateway_interface and gateway_base_url on aiproviders for "
    "Bifrost native vs LiteLLM shim routing."
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
    if not _column_exists(db, "aiproviders", "gateway_interface"):
        db.execute(
            text(
                """
                ALTER TABLE aiproviders
                ADD COLUMN gateway_interface VARCHAR(20) NOT NULL DEFAULT 'inherit'
                """
            )
        )
        print("Added aiproviders.gateway_interface (varchar, default 'inherit')")

    if not _column_exists(db, "aiproviders", "gateway_base_url"):
        db.execute(
            text(
                """
                ALTER TABLE aiproviders
                ADD COLUMN gateway_base_url VARCHAR(512) NULL
                """
            )
        )
        print("Added aiproviders.gateway_base_url (varchar, nullable)")


def downgrade(db: Session):
    if _column_exists(db, "aiproviders", "gateway_base_url"):
        db.execute(text("ALTER TABLE aiproviders DROP COLUMN gateway_base_url"))
        print("Dropped aiproviders.gateway_base_url")

    if _column_exists(db, "aiproviders", "gateway_interface"):
        db.execute(text("ALTER TABLE aiproviders DROP COLUMN gateway_interface"))
        print("Dropped aiproviders.gateway_interface")
