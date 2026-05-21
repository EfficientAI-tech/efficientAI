"""Migration: Persist diarised speaker turns + a per-row swap toggle.

Adds two columns to ``call_import_rows`` so the diarisation worker can
write structured speaker turns next to the plain ``diarised_transcript``
text it already produces:

  * ``diarised_segments`` (JSONB, NULL) — structured turn list shaped
    ``[{ "speaker": "agent"|"user"|"speaker_3", "text": "...",
         "start": float, "end": float, "raw_speaker": "Speaker 1" }, ...]``
    (one entry per pyannote-detected segment). Source of truth that the
    swap endpoint and the CSV export both read from when re-rendering
    the human-readable transcript string.
  * ``diarised_speaker_swap`` (BOOLEAN, NOT NULL, default FALSE) — when
    true the ``agent`` <-> ``user`` mapping in ``diarised_segments`` is
    inverted at render time (the canonical mapping written by the worker
    follows the "first speaker is the agent" heuristic; the swap toggle
    lets reviewers correct that without re-running diarisation).

Idempotent: every step checks for prior existence before applying, so a
rerun on a partially-upgraded database is safe. No backfill is needed —
legacy rows keep ``diarised_segments = NULL`` (the API treats that the
same as "no structured turns available, fall back to the plain text in
``diarised_transcript``").
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add diarised_segments JSONB and diarised_speaker_swap BOOLEAN to "
    "call_import_rows so the diarisation worker can persist speaker "
    "turns and reviewers can flip the user<->agent mapping."
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
    if not _table_exists(db, "call_import_rows"):
        # Fresh database where the parent table hasn't materialised yet
        # (the model's create_all will add both columns). Nothing to do.
        return

    if not _column_exists(db, "call_import_rows", "diarised_segments"):
        db.execute(
            text(
                "ALTER TABLE call_import_rows "
                "ADD COLUMN diarised_segments JSONB NULL"
            )
        )
        print("Added call_import_rows.diarised_segments")

    if not _column_exists(db, "call_import_rows", "diarised_speaker_swap"):
        db.execute(
            text(
                "ALTER TABLE call_import_rows "
                "ADD COLUMN diarised_speaker_swap BOOLEAN NOT NULL "
                "DEFAULT FALSE"
            )
        )
        print("Added call_import_rows.diarised_speaker_swap")
    else:
        # Belt-and-braces in case the column was created via
        # ``Base.metadata.create_all`` (which doesn't emit DEFAULT for a
        # Python-side default). Patch the server default in now so
        # future raw-SQL inserts don't trip the NOT NULL constraint.
        db.execute(
            text(
                "ALTER TABLE call_import_rows "
                "ALTER COLUMN diarised_speaker_swap SET DEFAULT FALSE"
            )
        )

    db.commit()
    print("Diarised speaker-turn columns are in place")


def downgrade(db: Session):
    for column in ("diarised_speaker_swap", "diarised_segments"):
        db.execute(
            text(
                f"ALTER TABLE call_import_rows DROP COLUMN IF EXISTS {column}"
            )
        )
    db.commit()
