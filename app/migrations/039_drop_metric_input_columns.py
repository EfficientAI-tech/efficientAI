"""Migration: Drop ``metrics.input_columns``.

The "column-input judge" feature (per-metric allow-list of CSV columns
the call-import worker would feed to the LLM in place of the transcript)
has been removed. The product now injects EVERY non-empty CSV cell into
the evaluation prompt for every metric (see ``_build_all_columns_block``
in ``app.workers.tasks.evaluate_call_import_row``), so the per-metric
allow-list is redundant — every column the user uploaded is already in
the prompt and the LLM picks the relevant ones based on the metric's
description.

Schema change: drop ``metrics.input_columns`` (JSON, NOT NULL DEFAULT
``'[]'``). The corresponding ORM column has been removed from
``app.models.database.Metric`` and the Pydantic schemas + frontend
no longer surface the field, so any code path that previously read the
column was already cleaned up before this migration runs.

Idempotent: existence-check before the DROP, so re-running on a
partially-upgraded database is a no-op. ``downgrade()`` re-creates the
column with the original default so a rollback restores the schema (the
per-row data is not recovered — it was an allow-list, not user data).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


description = (
    "Drop metrics.input_columns — the column-input judge feature has "
    "been removed in favour of injecting every CSV column into the "
    "evaluation prompt for every metric."
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
    if not _table_exists(db, "metrics"):
        # Fresh database — nothing to drop. ``Base.metadata.create_all``
        # already reflects the post-removal schema.
        return

    if _column_exists(db, "metrics", "input_columns"):
        db.execute(text("ALTER TABLE metrics DROP COLUMN input_columns"))
        print("Dropped metrics.input_columns")
    else:
        print("metrics.input_columns already absent — nothing to drop")

    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "metrics"):
        return

    if not _column_exists(db, "metrics", "input_columns"):
        # Recreate with the original shape so a rollback gets back the
        # exact column definition that 034_metric_input_columns.py
        # created. Per-row data is not restored (the feature was an
        # allow-list, not user content).
        db.execute(
            text(
                "ALTER TABLE metrics "
                "ADD COLUMN input_columns JSON NOT NULL DEFAULT '[]'::json"
            )
        )
        print("Recreated metrics.input_columns")

    db.commit()
