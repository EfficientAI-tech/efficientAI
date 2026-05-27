"""Migration: persist ``transcribe_mode`` on call-import rows + evaluations.

Adds a single ``transcribe_mode`` column to two tables so the diarisation
pipeline can branch between the two-stage STT+LLM path (existing
behaviour, kept as the default) and the new single-stage LLM-only path
where audio is fed directly to a multimodal chat model:

* ``call_import_rows.transcribe_mode`` VARCHAR(20) NOT NULL DEFAULT
  'stt_llm' — the mode the diarisation worker used for THIS row. Persisted
  so the row detail panel can surface "Diarised via LLM only (Gemini
  1.5 Pro)" without inferring from missing columns. Existing rows keep
  the default and continue to behave exactly as before.
* ``call_import_evaluations.transcribe_mode`` VARCHAR(20) NOT NULL DEFAULT
  'stt_llm' — the mode the run was *created* with. Retry chains read this
  to decide whether to enqueue a transcribe step with STT or with the
  multimodal LLM directly. Persisting it on the run (not just the row)
  also means a run that started in llm_only mode keeps that contract
  when its rows are retried later, even if the user never re-enters the
  modal.

The column type / default mirror the ``Literal["stt_llm", "llm_only"]``
contract in the matching Pydantic schemas. The CHECK constraint is
intentionally NOT enforced at the DB level — that level of validation
already happens in :class:`CallImportTranscribeRequest` / the route, and
keeping the DB column free-form lets us add a third mode (e.g. an
ASR-only diariser) later without another migration.

Idempotent: each step gates on
``information_schema.columns`` so a rerun on a partially-upgraded
database is safe. ``downgrade()`` drops the columns in reverse order.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


description = (
    "Add transcribe_mode column to call_import_rows and "
    "call_import_evaluations so the diarisation pipeline can record "
    "whether STT+LLM or the new LLM-only multimodal path was used."
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


def _add_transcribe_mode(db: Session, table: str) -> None:
    if not _table_exists(db, table):
        return
    if _column_exists(db, table, "transcribe_mode"):
        # Belt-and-braces: if the column was already created by
        # ``Base.metadata.create_all`` (which doesn't emit DEFAULT for
        # a Python-side default), reapply the server default so
        # future raw-SQL inserts don't trip the NOT NULL constraint.
        db.execute(
            text(
                f"ALTER TABLE {table} "
                "ALTER COLUMN transcribe_mode SET DEFAULT 'stt_llm'"
            )
        )
        return
    db.execute(
        text(
            f"ALTER TABLE {table} "
            "ADD COLUMN transcribe_mode VARCHAR(20) NOT NULL "
            "DEFAULT 'stt_llm'"
        )
    )
    print(f"Added {table}.transcribe_mode")


def upgrade(db: Session):
    _add_transcribe_mode(db, "call_import_rows")
    _add_transcribe_mode(db, "call_import_evaluations")
    db.commit()
    print("transcribe_mode columns are in place")


def downgrade(db: Session):
    for table in ("call_import_evaluations", "call_import_rows"):
        if _column_exists(db, table, "transcribe_mode"):
            db.execute(
                text(f"ALTER TABLE {table} DROP COLUMN transcribe_mode")
            )
    db.commit()
