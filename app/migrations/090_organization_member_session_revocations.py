"""Track minimum session epoch after org membership removal."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add organization_member_session_revocations"


def upgrade(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS organization_member_session_revocations (
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE CASCADE,
                user_id UUID NOT NULL
                    REFERENCES users(id) ON DELETE CASCADE,
                min_session_epoch INTEGER NOT NULL DEFAULT 1,
                revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (organization_id, user_id)
            )
            """
        )
    )


def downgrade(db: Session) -> None:
    db.execute(
        text(
            """
            DROP TABLE IF EXISTS organization_member_session_revocations
            """
        )
    )
