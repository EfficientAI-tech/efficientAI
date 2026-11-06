"""Ensure knowledge_chunks.id has a DB default (init_db tables may omit it)."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "knowledge_chunks id default"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE knowledge_chunks
                ALTER COLUMN id SET DEFAULT gen_random_uuid()
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE knowledge_chunks
                ALTER COLUMN id DROP DEFAULT
            """
        )
    )
    db.commit()
