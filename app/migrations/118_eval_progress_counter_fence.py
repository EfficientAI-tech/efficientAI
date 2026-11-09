"""Fence columns for Redis-buffered evaluation progress counters.

* ``call_import_evaluations.progress_counter_gen`` is bumped by every fenced
  shard recount. A flush carrying an older gen is ignored.
* ``call_import_evaluations.progress_flush_seq`` is the last applied flush
  sequence, so re-sending the same pending batch is a no-op.
* ``call_import_evaluation_rows (evaluation_id, status)`` makes the shard
  recounts (total / completed / failed / in-progress) index-only friendly.

Runs on every engine: the catalog gets the columns, shards get the index.
Each step is skipped when its table is not present on that engine.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Eval progress counter gen/seq columns and (evaluation_id, status) index"
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
    if _table_exists(db, "call_import_evaluations"):
        db.execute(
            text(
                """
                ALTER TABLE call_import_evaluations
                    ADD COLUMN IF NOT EXISTS progress_counter_gen INTEGER NOT NULL DEFAULT 0
                """
            )
        )
        db.execute(
            text(
                """
                ALTER TABLE call_import_evaluations
                    ADD COLUMN IF NOT EXISTS progress_flush_seq BIGINT NOT NULL DEFAULT 0
                """
            )
        )
    if _table_exists(db, "call_import_evaluation_rows"):
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_call_import_evaluation_rows_evaluation_status
                    ON call_import_evaluation_rows (evaluation_id, status)
                """
            )
        )
    db.commit()


def downgrade(db: Session):
    if _table_exists(db, "call_import_evaluation_rows"):
        db.execute(
            text("DROP INDEX IF EXISTS ix_call_import_evaluation_rows_evaluation_status")
        )
    if _table_exists(db, "call_import_evaluations"):
        db.execute(
            text(
                "ALTER TABLE call_import_evaluations DROP COLUMN IF EXISTS progress_flush_seq"
            )
        )
        db.execute(
            text(
                "ALTER TABLE call_import_evaluations DROP COLUMN IF EXISTS progress_counter_gen"
            )
        )
    db.commit()
