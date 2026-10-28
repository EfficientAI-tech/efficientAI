"""
Idempotent repair for recording_duration_seconds on shard DBs.

Migration 108 originally used MIGRATION_SCOPE=catalog, so some shard databases
never received the column while the catalog did. After 108 was corrected to
``all``, fresh shard runs apply 108. This migration is a no-op when the column
already exists and is safe on every engine (catalog + shards).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Ensure recording_duration_seconds exists on call_import_rows (shard repair)"
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
                ADD COLUMN IF NOT EXISTS recording_duration_seconds INTEGER
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.commit()
