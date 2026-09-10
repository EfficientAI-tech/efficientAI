"""Persist authenticated_org_epochs on refresh tokens for cross-org auth validation."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add authenticated_org_epochs to refresh_tokens"


def upgrade(db: Session) -> None:
    db.execute(
        text(
            """
            ALTER TABLE refresh_tokens
            ADD COLUMN IF NOT EXISTS authenticated_org_epochs JSONB
            """
        )
    )


def downgrade(db: Session) -> None:
    db.execute(
        text(
            """
            ALTER TABLE refresh_tokens
            DROP COLUMN IF EXISTS authenticated_org_epochs
            """
        )
    )
