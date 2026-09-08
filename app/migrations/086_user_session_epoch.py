"""Add session_epoch to users for global session invalidation on password change."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add users.session_epoch for password-change session invalidation"

MIGRATION_SCOPE = "catalog"


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = :column_name
            )
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


def upgrade(db: Session) -> None:
    if not _column_exists(db, "users", "session_epoch"):
        db.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0
                """
            )
        )


def downgrade(db: Session) -> None:
    if _column_exists(db, "users", "session_epoch"):
        db.execute(text("ALTER TABLE users DROP COLUMN session_epoch"))
