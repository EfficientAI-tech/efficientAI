"""Repair usage context after 119 and build read indexes without blocking writes."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Collision-safe usage context repair, shard orphan backfill, and concurrent read indexes"
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
        print("llm_usage_daily missing; skipping 120")
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
    print("Repaired usage rollup context and read indexes")


def downgrade(db: Session):
    db.commit()
