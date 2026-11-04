"""Durable batch checkpoints for evaluation analysis jobs (insights, clusters, prompts)."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add evaluation_analysis_batches checkpoint table"
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
    if _table_exists(db, "evaluation_analysis_batches"):
        db.commit()
        return
    db.execute(
        text(
            """
            CREATE TABLE evaluation_analysis_batches (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                evaluation_id UUID NOT NULL
                    REFERENCES call_import_evaluations(id) ON DELETE CASCADE,
                job_kind VARCHAR(32) NOT NULL,
                job_run_id UUID NOT NULL,
                batch_index INTEGER NOT NULL,
                cursor_row_index INTEGER NULL,
                cursor_evaluation_row_id UUID NULL,
                transcript_source VARCHAR(16) NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'completed',
                payload JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_evaluation_analysis_batch
                    UNIQUE (evaluation_id, job_kind, job_run_id, batch_index)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_evaluation_analysis_batches_eval_run
                ON evaluation_analysis_batches (evaluation_id, job_kind, job_run_id)
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "evaluation_analysis_batches"):
        db.commit()
        return
    db.execute(text("DROP TABLE IF EXISTS evaluation_analysis_batches"))
    db.commit()
