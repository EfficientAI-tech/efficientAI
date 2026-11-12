"""Backfill call-import context keys and add rollup indexes for usage reads."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Backfill llm_usage_daily call_import_id/evaluation_id and add read indexes"
)
MIGRATION_SCOPE = "catalog"


def _table_exists(db: Session, table: str) -> bool:
    return (
        db.execute(
            text(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :table_name
                """
            ),
            {"table_name": table},
        ).first()
        is not None
    )


def upgrade(db: Session):
    if not _table_exists(db, "llm_usage_daily"):
        print("llm_usage_daily missing; skipping 119")
        db.commit()
        return
    from app.services.usage.rollup_maintenance import (
        backfill_usage_context_keys,
        ensure_usage_read_indexes,
        repair_orphaned_row_context,
    )

    backfill_usage_context_keys(db)
    repair_orphaned_row_context(db)
    ensure_usage_read_indexes(db)
    print("Backfilled usage context keys and ensured usage read indexes")


def downgrade(db: Session):
    if not _table_exists(db, "llm_usage_daily"):
        db.commit()
        return
    from app.services.usage.rollup_maintenance import READ_INDEX_NAMES

    for index in READ_INDEX_NAMES:
        db.execute(text(f"DROP INDEX IF EXISTS {index}"))
    db.commit()
