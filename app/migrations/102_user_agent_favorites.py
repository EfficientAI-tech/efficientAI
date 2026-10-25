"""Per-user stars on agents. Each person keeps their own list."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "user_agent_favorites table"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS user_agent_favorites (
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ DEFAULT now(),
                PRIMARY KEY (user_id, agent_id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_user_agent_favorites_user_workspace
            ON user_agent_favorites (user_id, workspace_id)
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS user_agent_favorites"))
    db.commit()
