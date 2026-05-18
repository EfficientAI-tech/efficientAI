"""Migration: Diarization + configurable evaluation LLM for Call Imports.

Adds two related sets of columns:

  * ``call_import_rows.transcript_source / transcript_provider /
    transcript_model / transcript_status / transcript_error /
    transcribed_at`` — let the worker (and the UI) tell users whether a
    row's transcript came from the CSV or was diarized post-hoc, and
    surface diarization progress / errors per row.
  * ``call_import_evaluations.llm_provider / llm_model /
    llm_credential_id / metric_llm_overrides / stt_provider / stt_model
    / stt_credential_id`` — record the run-level LLM (and any per-metric
    override) the user picked from the Run Evaluation modal so we no
    longer hard-code OpenAI/gpt-4o, plus the STT credentials chosen when
    the run auto-transcribed missing transcripts before scoring.

Idempotent: every step checks for prior existence before applying so a
rerun on a partially-upgraded database is safe.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add transcription/diarization metadata to call_import_rows and "
    "configurable LLM/STT settings to call_import_evaluations"
)


def _column_exists(db: Session, table: str, column: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table, "column_name": column},
    ).first()
    return row is not None


def _table_exists(db: Session, table: str) -> bool:
    row = db.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": table},
    ).first()
    return row is not None


def upgrade(db: Session):
    # --- call_import_rows: transcription metadata ---
    if _table_exists(db, "call_import_rows"):
        if not _column_exists(db, "call_import_rows", "transcript_source"):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN transcript_source VARCHAR(20) NULL"
                )
            )
            print("Added call_import_rows.transcript_source")
        if not _column_exists(db, "call_import_rows", "transcript_provider"):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN transcript_provider VARCHAR(50) NULL"
                )
            )
            print("Added call_import_rows.transcript_provider")
        if not _column_exists(db, "call_import_rows", "transcript_model"):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN transcript_model VARCHAR(100) NULL"
                )
            )
            print("Added call_import_rows.transcript_model")
        if not _column_exists(db, "call_import_rows", "transcript_status"):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN transcript_status VARCHAR(20) "
                    "NOT NULL DEFAULT 'idle'"
                )
            )
            print("Added call_import_rows.transcript_status")
        if not _column_exists(db, "call_import_rows", "transcript_error"):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN transcript_error TEXT NULL"
                )
            )
            print("Added call_import_rows.transcript_error")
        if not _column_exists(db, "call_import_rows", "transcribed_at"):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN transcribed_at TIMESTAMP WITH TIME ZONE NULL"
                )
            )
            print("Added call_import_rows.transcribed_at")

        # Backfill: rows whose transcript was supplied via the CSV mapping
        # should be marked source='csv' so the UI can render the right
        # badge from day one. Treat blank/NULL transcripts as untouched
        # (status stays 'idle', source stays NULL).
        db.execute(
            text(
                """
                UPDATE call_import_rows
                SET transcript_source = 'csv'
                WHERE transcript IS NOT NULL
                  AND length(trim(transcript)) > 0
                  AND transcript_source IS NULL
                """
            )
        )

    # --- call_import_evaluations: configurable LLM + STT ---
    if _table_exists(db, "call_import_evaluations"):
        if not _column_exists(db, "call_import_evaluations", "llm_provider"):
            db.execute(
                text(
                    "ALTER TABLE call_import_evaluations "
                    "ADD COLUMN llm_provider VARCHAR(50) NULL"
                )
            )
            print("Added call_import_evaluations.llm_provider")
        if not _column_exists(db, "call_import_evaluations", "llm_model"):
            db.execute(
                text(
                    "ALTER TABLE call_import_evaluations "
                    "ADD COLUMN llm_model VARCHAR(100) NULL"
                )
            )
            print("Added call_import_evaluations.llm_model")
        if not _column_exists(db, "call_import_evaluations", "llm_credential_id"):
            db.execute(
                text(
                    """
                    ALTER TABLE call_import_evaluations
                    ADD COLUMN llm_credential_id UUID NULL
                        REFERENCES aiproviders(id) ON DELETE SET NULL
                    """
                )
            )
            print("Added call_import_evaluations.llm_credential_id")
        if not _column_exists(
            db, "call_import_evaluations", "metric_llm_overrides"
        ):
            db.execute(
                text(
                    "ALTER TABLE call_import_evaluations "
                    "ADD COLUMN metric_llm_overrides JSONB NULL"
                )
            )
            print("Added call_import_evaluations.metric_llm_overrides")
        if not _column_exists(db, "call_import_evaluations", "stt_provider"):
            db.execute(
                text(
                    "ALTER TABLE call_import_evaluations "
                    "ADD COLUMN stt_provider VARCHAR(50) NULL"
                )
            )
            print("Added call_import_evaluations.stt_provider")
        if not _column_exists(db, "call_import_evaluations", "stt_model"):
            db.execute(
                text(
                    "ALTER TABLE call_import_evaluations "
                    "ADD COLUMN stt_model VARCHAR(100) NULL"
                )
            )
            print("Added call_import_evaluations.stt_model")
        if not _column_exists(
            db, "call_import_evaluations", "stt_credential_id"
        ):
            db.execute(
                text(
                    "ALTER TABLE call_import_evaluations "
                    "ADD COLUMN stt_credential_id UUID NULL"
                )
            )
            print("Added call_import_evaluations.stt_credential_id")

    db.commit()
    print(
        "Call import diarization + configurable evaluation LLM schema "
        "is in place"
    )


def downgrade(db: Session):
    for column in (
        "stt_credential_id",
        "stt_model",
        "stt_provider",
        "metric_llm_overrides",
        "llm_credential_id",
        "llm_model",
        "llm_provider",
    ):
        db.execute(
            text(
                f"ALTER TABLE call_import_evaluations DROP COLUMN IF EXISTS {column}"
            )
        )

    for column in (
        "transcribed_at",
        "transcript_error",
        "transcript_status",
        "transcript_model",
        "transcript_provider",
        "transcript_source",
    ):
        db.execute(
            text(f"ALTER TABLE call_import_rows DROP COLUMN IF EXISTS {column}")
        )

    db.commit()
