"""Migration: per-credential enabled model allowlist for integrations."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add enabled_models JSONB to aiproviders"


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


def upgrade(db: Session) -> None:
    if not _column_exists(db, "aiproviders", "enabled_models"):
        db.execute(
            text(
                """
                ALTER TABLE aiproviders
                ADD COLUMN enabled_models JSONB NULL
                """
            )
        )


def downgrade(db: Session) -> None:
    if _column_exists(db, "aiproviders", "enabled_models"):
        db.execute(text("ALTER TABLE aiproviders DROP COLUMN enabled_models"))
