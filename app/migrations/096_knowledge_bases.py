"""Knowledge bases, documents, chunks (pgvector), and agent attachments."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "knowledge bases with pgvector chunks and agent links"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                status VARCHAR(32) NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_by VARCHAR
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_knowledge_bases_org_ws
                ON knowledge_bases (organization_id, workspace_id)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                source_type VARCHAR(32) NOT NULL DEFAULT 'file',
                original_filename VARCHAR(512),
                blob_key VARCHAR(1024) NOT NULL,
                content_type VARCHAR(255),
                byte_size BIGINT,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                error_text TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_knowledge_documents_kb
                ON knowledge_documents (knowledge_base_id)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                document_id UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                page_number INTEGER,
                embedding vector(1536),
                embedding_model VARCHAR(128),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    # init_db() may have created knowledge_chunks from SQLAlchemy models before
    # this migration runs (models omit the vector column). Ensure embedding exists.
    db.execute(
        text(
            """
            ALTER TABLE knowledge_chunks
                ADD COLUMN IF NOT EXISTS embedding vector(1536)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_document
                ON knowledge_chunks (document_id)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding
                ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS agent_knowledge_bases (
                agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (agent_id, knowledge_base_id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_agent_knowledge_bases_kb
                ON agent_knowledge_bases (knowledge_base_id)
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS agent_knowledge_bases"))
    db.execute(text("DROP TABLE IF EXISTS knowledge_chunks"))
    db.execute(text("DROP TABLE IF EXISTS knowledge_documents"))
    db.execute(text("DROP TABLE IF EXISTS knowledge_bases"))
    db.commit()
