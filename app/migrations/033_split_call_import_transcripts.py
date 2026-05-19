"""Migration: Split production vs diarised transcripts on call_import_rows.

Historically ``call_import_rows.transcript`` was a single text column that
got overwritten whenever a user kicked off the diarisation/transcription
worker. That meant a CSV-supplied "production" transcript was silently
replaced by whatever the STT provider produced, and the export only had
one transcript column to choose from.

This migration splits the storage so:

  * ``call_import_rows.transcript`` becomes the "production" transcript
    (the one supplied via the CSV upload).
  * ``call_import_rows.diarised_transcript`` (new) holds whatever the
    diarisation worker writes back, along with companion metadata
    columns (``diarised_transcript_provider``, ``diarised_transcript_model``,
    ``diarised_transcript_status``, ``diarised_transcript_error``,
    ``diarised_at``) that mirror the existing transcription fields.
  * ``call_import_evaluations.transcript_source`` (new) records which
    of the two transcripts a given evaluation run scored against
    (``'production'`` | ``'diarised'``). Defaults to ``'production'`` so
    historical runs keep their semantics.

Backfill: rows whose previous worker run filled the single transcript
column (``transcript_source = 'transcribed'``) are migrated so the
worker-produced text + metadata moves into the new ``diarised_*``
columns and ``transcript`` is reset to NULL. CSV-sourced rows
(``transcript_source = 'csv'`` or NULL with a non-empty transcript) are
left untouched — their value is the production transcript by
definition.

Idempotent: every step checks for prior existence before applying so a
rerun on a partially-upgraded database is safe.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add diarised_transcript columns to call_import_rows + transcript_source "
    "to call_import_evaluations; backfill worker-produced transcripts into "
    "the new diarised_* fields."
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
    # --- call_import_rows: new diarised_* columns ---
    if _table_exists(db, "call_import_rows"):
        if not _column_exists(db, "call_import_rows", "diarised_transcript"):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN diarised_transcript TEXT NULL"
                )
            )
            print("Added call_import_rows.diarised_transcript")
        if not _column_exists(
            db, "call_import_rows", "diarised_transcript_provider"
        ):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN diarised_transcript_provider VARCHAR(50) NULL"
                )
            )
            print("Added call_import_rows.diarised_transcript_provider")
        if not _column_exists(
            db, "call_import_rows", "diarised_transcript_model"
        ):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN diarised_transcript_model VARCHAR(100) NULL"
                )
            )
            print("Added call_import_rows.diarised_transcript_model")
        if not _column_exists(
            db, "call_import_rows", "diarised_transcript_status"
        ):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN diarised_transcript_status VARCHAR(20) "
                    "NOT NULL DEFAULT 'idle'"
                )
            )
            print("Added call_import_rows.diarised_transcript_status")
        if not _column_exists(
            db, "call_import_rows", "diarised_transcript_error"
        ):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN diarised_transcript_error TEXT NULL"
                )
            )
            print("Added call_import_rows.diarised_transcript_error")
        if not _column_exists(db, "call_import_rows", "diarised_at"):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "ADD COLUMN diarised_at TIMESTAMP WITH TIME ZONE NULL"
                )
            )
            print("Added call_import_rows.diarised_at")

        # Backfill worker-produced transcripts into the new fields so
        # the production ``transcript`` column reverts to its
        # CSV-only meaning going forward. We move the value AND the
        # accompanying metadata (provider/model/status/error/at) so
        # the UI badge ("Diarised via deepgram/nova-2") keeps working
        # without code changes.
        db.execute(
            text(
                """
                UPDATE call_import_rows
                SET diarised_transcript = transcript,
                    diarised_transcript_provider = transcript_provider,
                    diarised_transcript_model = transcript_model,
                    diarised_transcript_status = 'completed',
                    diarised_transcript_error = NULL,
                    diarised_at = transcribed_at,
                    transcript = NULL,
                    transcript_provider = NULL,
                    transcript_model = NULL,
                    transcript_status = 'idle',
                    transcript_error = NULL,
                    transcribed_at = NULL,
                    transcript_source = NULL
                WHERE transcript_source = 'transcribed'
                """
            )
        )

    # --- call_import_evaluations: transcript_source ---
    if _table_exists(db, "call_import_evaluations"):
        if not _column_exists(
            db, "call_import_evaluations", "transcript_source"
        ):
            db.execute(
                text(
                    "ALTER TABLE call_import_evaluations "
                    "ADD COLUMN transcript_source VARCHAR(20) "
                    "NOT NULL DEFAULT 'production'"
                )
            )
            print("Added call_import_evaluations.transcript_source")

    db.commit()
    print(
        "Split production/diarised transcript schema is in place"
    )


def downgrade(db: Session):
    # Best-effort merge back: copy any diarised content into the
    # production ``transcript`` column so downstream code that still
    # expects a single field keeps working.
    if _table_exists(db, "call_import_rows") and _column_exists(
        db, "call_import_rows", "diarised_transcript"
    ):
        db.execute(
            text(
                """
                UPDATE call_import_rows
                SET transcript = COALESCE(transcript, diarised_transcript),
                    transcript_provider = COALESCE(
                        transcript_provider, diarised_transcript_provider
                    ),
                    transcript_model = COALESCE(
                        transcript_model, diarised_transcript_model
                    ),
                    transcript_status = CASE
                        WHEN transcript IS NULL AND diarised_transcript IS NOT NULL
                            THEN 'completed'
                        ELSE transcript_status
                    END,
                    transcribed_at = COALESCE(transcribed_at, diarised_at),
                    transcript_source = CASE
                        WHEN transcript IS NULL AND diarised_transcript IS NOT NULL
                            THEN 'transcribed'
                        ELSE transcript_source
                    END
                WHERE diarised_transcript IS NOT NULL
                """
            )
        )

    for column in (
        "diarised_at",
        "diarised_transcript_error",
        "diarised_transcript_status",
        "diarised_transcript_model",
        "diarised_transcript_provider",
        "diarised_transcript",
    ):
        db.execute(
            text(f"ALTER TABLE call_import_rows DROP COLUMN IF EXISTS {column}")
        )

    db.execute(
        text(
            "ALTER TABLE call_import_evaluations "
            "DROP COLUMN IF EXISTS transcript_source"
        )
    )

    db.commit()
