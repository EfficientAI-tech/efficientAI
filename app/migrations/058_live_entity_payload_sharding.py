"""
Migration: Live call / evaluator result payload sharding.

Adds ``shard_id`` on catalog headers and payload tables on catalog + data shards
(``MIGRATION_SCOPE = all``). Heavy JSON/text can be dual-written to shards when
``database.sharding.enabled`` is true.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add shard_id to call_recordings/evaluator_results and payload tables "
    "for live-entity sharding."
)

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
            SELECT 1 FROM information_schema.tables WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _column_exists(db, "evaluator_results", "shard_id"):
        db.execute(
            text(
                """
                ALTER TABLE evaluator_results
                ADD COLUMN shard_id VARCHAR(64) NULL
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_evaluator_results_shard_id
                ON evaluator_results (shard_id)
                """
            )
        )

    if not _column_exists(db, "call_recordings", "shard_id"):
        db.execute(
            text(
                """
                ALTER TABLE call_recordings
                ADD COLUMN shard_id VARCHAR(64) NULL
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_call_recordings_shard_id
                ON call_recordings (shard_id)
                """
            )
        )

    if not _table_exists(db, "evaluator_result_payloads"):
        db.execute(
            text(
                """
                CREATE TABLE evaluator_result_payloads (
                    evaluator_result_id UUID PRIMARY KEY,
                    workspace_id UUID NOT NULL,
                    audio_s3_key VARCHAR NULL,
                    transcription TEXT NULL,
                    speaker_segments JSONB NULL,
                    metric_scores JSONB NULL,
                    call_data JSONB NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_evaluator_result_payloads_workspace_id
                ON evaluator_result_payloads (workspace_id)
                """
            )
        )

    if not _table_exists(db, "call_recording_payloads"):
        db.execute(
            text(
                """
                CREATE TABLE call_recording_payloads (
                    call_recording_id UUID PRIMARY KEY,
                    workspace_id UUID NOT NULL,
                    call_data JSONB NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_call_recording_payloads_workspace_id
                ON call_recording_payloads (workspace_id)
                """
            )
        )

    db.commit()
    print("✓ Live entity payload sharding schema ready")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS call_recording_payloads"))
    db.execute(text("DROP TABLE IF EXISTS evaluator_result_payloads"))
    db.execute(text("DROP INDEX IF EXISTS ix_call_recordings_shard_id"))
    db.execute(text("ALTER TABLE call_recordings DROP COLUMN IF EXISTS shard_id"))
    db.execute(text("DROP INDEX IF EXISTS ix_evaluator_results_shard_id"))
    db.execute(text("ALTER TABLE evaluator_results DROP COLUMN IF EXISTS shard_id"))
    db.commit()
