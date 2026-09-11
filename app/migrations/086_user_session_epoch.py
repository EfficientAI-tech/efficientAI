"""Add session_epoch to users for global session invalidation on password change."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add users.session_epoch for password-change session invalidation"

MIGRATION_SCOPE = "catalog"


def upgrade(db: Session) -> None:
    db.execute(
        text(
            """
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS session_epoch INTEGER NOT NULL DEFAULT 0
            """
        )
    )


def downgrade(db: Session) -> None:
    db.execute(
        text(
            """
            ALTER TABLE users
            DROP COLUMN IF EXISTS session_epoch
            """
        )
    )
