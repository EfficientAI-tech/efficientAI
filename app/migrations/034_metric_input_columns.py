"""
Migration: Column-input judge metrics.

Adds:
  * ``metrics.input_columns`` (JSONB, NOT NULL, default ``'[]'::jsonb``) -
    list of CSV header strings (from ``call_import_rows.raw_columns``)
    that the LLM judge should read instead of the transcript. When empty
    the metric continues to score the transcript like today; when
    non-empty the worker injects those column values into the prompt as
    "Context inputs" for that row.

Idempotent: checks for prior existence before applying.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add input_columns JSONB to metrics so a metric can be evaluated "
    "against named columns from a call import's raw_columns instead of "
    "the transcript."
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
    if not _column_exists(db, "metrics", "input_columns"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN input_columns JSONB NOT NULL DEFAULT '[]'::jsonb
                """
            )
        )
        print("Added metrics.input_columns")
    else:
        print("metrics.input_columns already exists, skipping...")

    db.commit()
    print("input_columns is in place")


def downgrade(db: Session):
    db.execute(
        text("ALTER TABLE metrics DROP COLUMN IF EXISTS input_columns")
    )
    db.commit()
