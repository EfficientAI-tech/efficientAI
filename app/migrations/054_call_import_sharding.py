"""
Migration: Call-import sharding registry, workspace denorm, dispatch indexes.

Catalog table ``call_import_shard_slices`` records which shard owns each
slice of rows for an import. Denormalized ``workspace_id`` on row tables
supports shard-local queries without joining catalog parents.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add call_import_shard_slices registry, workspace_id on row tables, "
    "and dispatch indexes for evaluation and diarization workers."
)

# ``all`` until catalog/shard migration split (Phase 8 hardening).
MIGRATION_SCOPE = "all"


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _index_exists(db: Session, index_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM pg_indexes WHERE indexname = :index_name
            """
        ),
        {"index_name": index_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _table_exists(db, "call_import_shard_slices"):
        db.execute(
            text(
                """
                CREATE TABLE call_import_shard_slices (
                    call_import_id UUID NOT NULL
                        REFERENCES call_imports(id) ON DELETE CASCADE,
                    slice_id INTEGER NOT NULL,
                    shard_id VARCHAR(64) NOT NULL,
                    row_index_min INTEGER NOT NULL,
                    row_index_max INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (call_import_id, slice_id)
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX ix_call_import_shard_slices_shard
                ON call_import_shard_slices (shard_id, call_import_id)
                """
            )
        )
        print("Created call_import_shard_slices")

    if _table_exists(db, "call_import_rows") and not _column_exists(
        db, "call_import_rows", "workspace_id"
    ):
        db.execute(
            text(
                """
                ALTER TABLE call_import_rows
                ADD COLUMN workspace_id UUID NULL
                """
            )
        )
        db.execute(
            text(
                """
                UPDATE call_import_rows r
                SET workspace_id = c.workspace_id
                FROM call_imports c
                WHERE r.call_import_id = c.id AND r.workspace_id IS NULL
                """
            )
        )
        db.execute(
            text(
                """
                ALTER TABLE call_import_rows
                ALTER COLUMN workspace_id SET NOT NULL
                """
            )
        )
        db.execute(
            text(
                """
                ALTER TABLE call_import_rows
                ADD CONSTRAINT fk_call_import_rows_workspace
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX ix_call_import_rows_workspace_id
                ON call_import_rows (workspace_id)
                """
            )
        )
        print("Added call_import_rows.workspace_id")

    if _table_exists(db, "call_import_evaluation_rows") and not _column_exists(
        db, "call_import_evaluation_rows", "workspace_id"
    ):
        db.execute(
            text(
                """
                ALTER TABLE call_import_evaluation_rows
                ADD COLUMN workspace_id UUID NULL
                """
            )
        )
        db.execute(
            text(
                """
                UPDATE call_import_evaluation_rows er
                SET workspace_id = c.workspace_id
                FROM call_import_evaluations e
                JOIN call_imports c ON c.id = e.call_import_id
                WHERE er.evaluation_id = e.id AND er.workspace_id IS NULL
                """
            )
        )
        db.execute(
            text(
                """
                ALTER TABLE call_import_evaluation_rows
                ALTER COLUMN workspace_id SET NOT NULL
                """
            )
        )
        db.execute(
            text(
                """
                ALTER TABLE call_import_evaluation_rows
                ADD CONSTRAINT fk_call_import_eval_rows_workspace
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX ix_call_import_evaluation_rows_workspace_id
                ON call_import_evaluation_rows (workspace_id)
                """
            )
        )
        print("Added call_import_evaluation_rows.workspace_id")

    if _table_exists(db, "call_import_evaluation_rows") and not _index_exists(
        db, "ix_cier_eval_status_task"
    ):
        db.execute(
            text(
                """
                CREATE INDEX ix_cier_eval_status_task
                ON call_import_evaluation_rows (evaluation_id, status, celery_task_id)
                """
            )
        )
        print("Created ix_cier_eval_status_task")

    if _table_exists(db, "call_import_rows") and not _index_exists(
        db, "ix_cir_import_diarise_task"
    ):
        db.execute(
            text(
                """
                CREATE INDEX ix_cir_import_diarise_task
                ON call_import_rows (call_import_id, diarised_transcript_status, celery_task_id)
                """
            )
        )
        print("Created ix_cir_import_diarise_task")

    db.commit()


def downgrade(db: Session):
    if _index_exists(db, "ix_cir_import_diarise_task"):
        db.execute(text("DROP INDEX ix_cir_import_diarise_task"))
    if _index_exists(db, "ix_cier_eval_status_task"):
        db.execute(text("DROP INDEX ix_cier_eval_status_task"))
    if _column_exists(db, "call_import_evaluation_rows", "workspace_id"):
        db.execute(
            text(
                "ALTER TABLE call_import_evaluation_rows DROP COLUMN workspace_id"
            )
        )
    if _column_exists(db, "call_import_rows", "workspace_id"):
        db.execute(text("ALTER TABLE call_import_rows DROP COLUMN workspace_id"))
    if _table_exists(db, "call_import_shard_slices"):
        db.execute(text("DROP TABLE call_import_shard_slices"))
    db.commit()
