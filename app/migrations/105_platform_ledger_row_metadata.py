"""Keep recording date and list metadata on a platform reservation."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "platform ledger recording_date and raw_columns"
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
    if not _table_exists(db, "platform_conversation_ledger"):
        return
    db.execute(
        text(
            """
            ALTER TABLE platform_conversation_ledger
                ADD COLUMN IF NOT EXISTS recording_date DATE,
                ADD COLUMN IF NOT EXISTS raw_columns JSONB
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "platform_conversation_ledger"):
        return
    db.execute(
        text(
            """
            ALTER TABLE platform_conversation_ledger
                DROP COLUMN IF EXISTS raw_columns,
                DROP COLUMN IF EXISTS recording_date
            """
        )
    )
    db.commit()
