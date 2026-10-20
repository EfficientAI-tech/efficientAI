"""Audit table for live provider prompt pushes."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "prompt push audit table"
MIGRATION_SCOPE = "all"


def _table_exists(db: Session, name: str) -> bool:
    return (
        db.execute(
            text(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :name
                """
            ),
            {"name": name},
        ).first()
        is not None
    )


def upgrade(db: Session):
    if not _table_exists(db, "prompt_partials"):
        return
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS prompt_pushes (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL REFERENCES organizations(id),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                prompt_partial_id UUID NOT NULL REFERENCES prompt_partials(id) ON DELETE CASCADE,
                prompt_version INTEGER NOT NULL,
                provider VARCHAR(50) NOT NULL,
                external_agent_id VARCHAR(255) NOT NULL,
                external_agent_name VARCHAR(255),
                integration_id UUID REFERENCES integrations(id) ON DELETE SET NULL,
                evaluation_id UUID,
                pushed_by VARCHAR,
                status VARCHAR(20) NOT NULL,
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_prompt_pushes_partial
            ON prompt_pushes (prompt_partial_id, created_at DESC)
            """
        )
    )
