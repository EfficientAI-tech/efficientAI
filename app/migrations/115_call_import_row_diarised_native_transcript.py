"""Store the raw STT transcript used as the native-script WER/CER hypothesis."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add diarised_native_transcript to call_import_rows"
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
    db.execute(
        text(
            """
            ALTER TABLE call_import_rows
                ADD COLUMN IF NOT EXISTS diarised_native_transcript TEXT NULL
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "call_import_rows"):
        db.commit()
        return
    db.execute(
        text(
            """
            ALTER TABLE call_import_rows
                DROP COLUMN IF EXISTS diarised_native_transcript
            """
        )
    )
    db.commit()
