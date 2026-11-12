"""Separate knowledge bases for the production agent and the test agent.

Existing links were shared by both sides, so each is kept as a production link and
copied as a test link; users can then detach either side independently.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "agent_knowledge_bases.role (production | test)"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    has_role = db.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'agent_knowledge_bases' AND column_name = 'role'
            """)).first()
    if has_role:
        return
    db.execute(text("""
            ALTER TABLE agent_knowledge_bases
                ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'production'
            """))
    db.execute(text("""
            ALTER TABLE agent_knowledge_bases DROP CONSTRAINT IF EXISTS agent_knowledge_bases_pkey
            """))
    db.execute(text("""
            ALTER TABLE agent_knowledge_bases
                ADD PRIMARY KEY (agent_id, knowledge_base_id, role)
            """))
    db.execute(text("""
            INSERT INTO agent_knowledge_bases
                (agent_id, knowledge_base_id, organization_id, workspace_id, created_at, role)
            SELECT agent_id, knowledge_base_id, organization_id, workspace_id, created_at, 'test'
            FROM agent_knowledge_bases
            WHERE role = 'production'
            ON CONFLICT DO NOTHING
            """))
    db.commit()


def downgrade(db: Session):
    db.execute(text("DELETE FROM agent_knowledge_bases WHERE role <> 'production'"))
    db.execute(
        text(
            "ALTER TABLE agent_knowledge_bases DROP CONSTRAINT IF EXISTS agent_knowledge_bases_pkey"
        )
    )
    db.execute(text("ALTER TABLE agent_knowledge_bases DROP COLUMN IF EXISTS role"))
    db.execute(
        text("ALTER TABLE agent_knowledge_bases ADD PRIMARY KEY (agent_id, knowledge_base_id)")
    )
    db.commit()
