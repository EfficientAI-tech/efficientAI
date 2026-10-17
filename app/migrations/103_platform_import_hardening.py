"""Columns and indexes for platform import leases, billing, and queued rows."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "platform import hardening columns"
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
    if _table_exists(db, "call_imports"):
        db.execute(
            text(
                """
                ALTER TABLE call_imports
                    ADD COLUMN IF NOT EXISTS billed_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS last_progress_at TIMESTAMPTZ
                """
            )
        )
    if _table_exists(db, "call_import_discovery_slices"):
        db.execute(
            text(
                """
                ALTER TABLE call_import_discovery_slices
                    ADD COLUMN IF NOT EXISTS agent_id VARCHAR(255)
                """
            )
        )
    if _table_exists(db, "call_import_rows"):
        db.execute(
            text(
                """
                ALTER TABLE call_import_rows
                    ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS download_started_at TIMESTAMPTZ
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_call_import_rows_queued_dispatch
                    ON call_import_rows (call_import_id)
                    WHERE status = 'pending' AND celery_task_id IS NOT NULL
                """
            )
        )
    db.commit()


def downgrade(db: Session):
    if _table_exists(db, "call_import_rows"):
        db.execute(text("DROP INDEX IF EXISTS ix_call_import_rows_queued_dispatch"))
        db.execute(
            text(
                """
                ALTER TABLE call_import_rows
                    DROP COLUMN IF EXISTS download_started_at,
                    DROP COLUMN IF EXISTS dispatched_at
                """
            )
        )
    if _table_exists(db, "call_import_discovery_slices"):
        db.execute(
            text(
                "ALTER TABLE call_import_discovery_slices DROP COLUMN IF EXISTS agent_id"
            )
        )
    if _table_exists(db, "call_imports"):
        db.execute(
            text(
                """
                ALTER TABLE call_imports
                    DROP COLUMN IF EXISTS last_progress_at,
                    DROP COLUMN IF EXISTS billed_at
                """
            )
        )
    db.commit()
