"""Migration: switch call-import diarisation from pyannote to an LLM.

Schema changes (all idempotent, gated on
``information_schema.columns``):

``call_import_rows``
* ``diarised_segments`` JSONB — structured turn list. (Originally
  introduced on the ORM but never persisted by a prior migration, so we
  add it here defensively for databases that pre-date the column.)
* ``diarised_speaker_swap`` BOOLEAN NOT NULL DEFAULT false — same
  back-fill rationale as above.
* ``diarised_llm_provider`` VARCHAR(50) — provider that diarised the
  row (``"openai"``, ``"anthropic"``, …). NULL on pre-feature rows.
* ``diarised_llm_model`` VARCHAR(100) — model name used.
* ``diarised_llm_credential_id`` UUID — optional credential pin (no FK
  because the same column is reused by both ``aiproviders`` and
  ``integrations``, matching the existing ``stt_credential_id`` pattern
  on ``call_import_evaluations``).
* ``diarised_prompt`` TEXT — the operator-supplied custom prompt (or
  the default) used for diarisation. Surfaced in the UI so reviewers
  can see what instructions produced the turns.

``call_import_evaluations`` (run-level defaults that get fanned out to
the per-row worker when the Run Evaluation modal auto-diarises rows
that are missing a diarised transcript):
* ``diarisation_llm_provider`` VARCHAR(50)
* ``diarisation_llm_model`` VARCHAR(100)
* ``diarisation_llm_credential_id`` UUID
* ``diarisation_prompt`` TEXT

``downgrade()`` drops the new columns in reverse order. The
``diarised_segments`` / ``diarised_speaker_swap`` pair is preserved on
downgrade because removing them would also remove the older
speaker-swap UI affordance — operators on a rollback path keep both.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


description = (
    "Add LLM diarisation columns to call_import_rows and "
    "call_import_evaluations (and back-fill diarised_segments / "
    "diarised_speaker_swap if missing)."
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


def _add_column(db: Session, table: str, column: str, ddl: str) -> None:
    if not _column_exists(db, table, column):
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        print(f"Added {table}.{column}")
    else:
        print(f"{table}.{column} already exists — skipping")


def _drop_column(db: Session, table: str, column: str) -> None:
    if _column_exists(db, table, column):
        db.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
        print(f"Dropped {table}.{column}")


def upgrade(db: Session):
    if _table_exists(db, "call_import_rows"):
        _add_column(db, "call_import_rows", "diarised_segments", "JSONB")
        _add_column(
            db,
            "call_import_rows",
            "diarised_speaker_swap",
            "BOOLEAN NOT NULL DEFAULT false",
        )
        _add_column(
            db, "call_import_rows", "diarised_llm_provider", "VARCHAR(50)"
        )
        _add_column(
            db, "call_import_rows", "diarised_llm_model", "VARCHAR(100)"
        )
        _add_column(
            db, "call_import_rows", "diarised_llm_credential_id", "UUID"
        )
        _add_column(db, "call_import_rows", "diarised_prompt", "TEXT")

    if _table_exists(db, "call_import_evaluations"):
        _add_column(
            db,
            "call_import_evaluations",
            "diarisation_llm_provider",
            "VARCHAR(50)",
        )
        _add_column(
            db,
            "call_import_evaluations",
            "diarisation_llm_model",
            "VARCHAR(100)",
        )
        _add_column(
            db,
            "call_import_evaluations",
            "diarisation_llm_credential_id",
            "UUID",
        )
        _add_column(
            db, "call_import_evaluations", "diarisation_prompt", "TEXT"
        )

    db.commit()


def downgrade(db: Session):
    if _table_exists(db, "call_import_evaluations"):
        _drop_column(
            db, "call_import_evaluations", "diarisation_prompt"
        )
        _drop_column(
            db, "call_import_evaluations", "diarisation_llm_credential_id"
        )
        _drop_column(
            db, "call_import_evaluations", "diarisation_llm_model"
        )
        _drop_column(
            db, "call_import_evaluations", "diarisation_llm_provider"
        )

    if _table_exists(db, "call_import_rows"):
        _drop_column(db, "call_import_rows", "diarised_prompt")
        _drop_column(db, "call_import_rows", "diarised_llm_credential_id")
        _drop_column(db, "call_import_rows", "diarised_llm_model")
        _drop_column(db, "call_import_rows", "diarised_llm_provider")

    db.commit()
