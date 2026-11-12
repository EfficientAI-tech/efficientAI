"""Add per–knowledge-base embedding model selection."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "knowledge_bases.embedding_model column"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE knowledge_bases
                ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(128)
                NOT NULL DEFAULT 'text-embedding-3-small'
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS embedding_model"))
    db.commit()
