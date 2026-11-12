"""GIN trigram indexes for call-import row text search."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "pg_trgm indexes on call_import_rows search columns"
MIGRATION_SCOPE = "all"


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _table_exists(db, "call_import_rows"):
        db.commit()
        return
    db.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_import_rows_conversation_id_trgm
                ON call_import_rows
                USING gin (conversation_id gin_trgm_ops)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_import_rows_transcript_trgm
                ON call_import_rows
                USING gin (transcript gin_trgm_ops)
                WHERE transcript IS NOT NULL
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_import_rows_diarised_transcript_trgm
                ON call_import_rows
                USING gin (diarised_transcript gin_trgm_ops)
                WHERE diarised_transcript IS NOT NULL
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "call_import_rows"):
        db.commit()
        return
    db.execute(text("DROP INDEX IF EXISTS ix_call_import_rows_diarised_transcript_trgm"))
    db.execute(text("DROP INDEX IF EXISTS ix_call_import_rows_transcript_trgm"))
    db.execute(text("DROP INDEX IF EXISTS ix_call_import_rows_conversation_id_trgm"))
    db.commit()
