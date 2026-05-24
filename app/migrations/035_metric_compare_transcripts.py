"""
Migration: Transcript-compare judge metrics.

Adds:
  * ``metrics.compare_transcripts`` (BOOLEAN, NOT NULL, default FALSE) -
    when TRUE the metric is a "transcript-compare judge": the
    call-import evaluator feeds BOTH ``call_import_rows.transcript``
    (production / CSV-supplied) and ``call_import_rows.diarised_transcript``
    (worker-produced) to the LLM as a labeled pair instead of feeding
    one transcript. The parent evaluation's ``transcript_source`` is
    ignored for these metrics — they always read both columns. v1
    keeps them standalone (no parent / no children); the schema
    validator enforces the mutual exclusion with ``input_columns``,
    ``parent_metric_id`` and ``selection_mode``.

Idempotent: checks for prior existence before applying.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add compare_transcripts BOOLEAN to metrics so a metric can be "
    "evaluated against the (production, diarised) transcript pair on "
    "each call-import row instead of a single transcript."
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


def upgrade(db: Session):
    if not _column_exists(db, "metrics", "compare_transcripts"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN compare_transcripts BOOLEAN NOT NULL
                    DEFAULT FALSE
                """
            )
        )
        print("Added metrics.compare_transcripts")
    else:
        # Belt-and-braces: if the column was created by
        # ``Base.metadata.create_all`` without the server-side default
        # (create_all doesn't emit DEFAULT clauses for Python-side
        # ``default=False``), patch the default in now so future
        # raw-SQL inserts don't trip the NOT NULL constraint.
        db.execute(
            text(
                "ALTER TABLE metrics ALTER COLUMN compare_transcripts "
                "SET DEFAULT FALSE"
            )
        )
        print(
            "metrics.compare_transcripts already exists, ensured "
            "DEFAULT FALSE"
        )

    db.commit()
    print("compare_transcripts is in place")


def downgrade(db: Session):
    db.execute(
        text(
            "ALTER TABLE metrics DROP COLUMN IF EXISTS compare_transcripts"
        )
    )
    db.commit()
