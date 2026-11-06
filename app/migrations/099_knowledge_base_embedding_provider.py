"""Per–knowledge-base embedding provider and credential (any LiteLLM embedding model)."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "knowledge_bases embedding provider + credential; widen model id columns"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE knowledge_bases
                ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(64)
                NOT NULL DEFAULT 'openai'
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE knowledge_bases
                ADD COLUMN IF NOT EXISTS embedding_credential_id UUID
                REFERENCES aiproviders(id) ON DELETE SET NULL
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE knowledge_bases
                ALTER COLUMN embedding_model TYPE VARCHAR(512)
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE knowledge_chunks
                ALTER COLUMN embedding_model TYPE VARCHAR(512)
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE knowledge_bases
                DROP COLUMN IF EXISTS embedding_credential_id
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE knowledge_bases
                DROP COLUMN IF EXISTS embedding_provider
            """
        )
    )
    db.commit()
