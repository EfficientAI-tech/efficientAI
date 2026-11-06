"""External tool connections (MCP servers, HTTP tools, Postgres) and their agent links."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "tool_connections + agent_tool_connections"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(text("""
            CREATE TABLE IF NOT EXISTS tool_connections (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(64) NOT NULL,
                connection_type VARCHAR(32) NOT NULL,
                preset VARCHAR(64),
                config JSON NOT NULL DEFAULT '{}',
                secrets TEXT,
                simulation_mode VARCHAR(16) NOT NULL DEFAULT 'mock_writes',
                cached_tools JSON,
                last_tested_at TIMESTAMPTZ,
                last_error TEXT,
                created_by VARCHAR,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """))
    db.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_tool_connections_workspace_slug
                ON tool_connections (workspace_id, slug)
            """))
    db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_tool_connections_org
                ON tool_connections (organization_id)
            """))
    db.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_tool_connections (
                agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                tool_connection_id UUID NOT NULL REFERENCES tool_connections(id) ON DELETE CASCADE,
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                enabled_tools JSON,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (agent_id, tool_connection_id)
            )
            """))
    db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_agent_tool_connections_connection
                ON agent_tool_connections (tool_connection_id)
            """))
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS agent_tool_connections"))
    db.execute(text("DROP TABLE IF EXISTS tool_connections"))
    db.commit()
