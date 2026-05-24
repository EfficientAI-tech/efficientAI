"""
Migration: Per-evaluation opt-in for top-level metric discovery.

Adds two columns to ``call_import_evaluations``:

  * ``discover_new_metrics`` (BOOLEAN, NOT NULL, default FALSE) — when
    true on a Call Import evaluation, the LLM is invited to propose
    brand-new top-level metrics (boolean / rating / category) it
    noticed in the transcripts. Candidates surface in a "Discovered
    metrics" panel at the top of the evaluation's Flow tab and can be
    promoted into real standalone ``Metric`` rows.
  * ``discovered_metric_aliases`` (JSONB, NOT NULL, default ``{}``) —
    flat slug-to-slug redirect map populated when the user merges or
    tombstones discovered metric candidates. Shape::

        { "<from_slug>": "<to_slug>", ... }

    Unlike ``discovered_label_aliases`` (which is nested per parent),
    this map is flat because top-level metric discovery is not scoped
    to a parent. An empty-string value tombstones the slug so workers
    finishing later can't re-introduce it.

Idempotent: each column is only added when not already present.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add discover_new_metrics flag + discovered_metric_aliases JSONB to "
    "call_import_evaluations for per-run top-level metric discovery"
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
        text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
        ),
        {"t": table},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _table_exists(db, "call_import_evaluations"):
        print(
            "Skipping 037: call_import_evaluations table is not present yet"
        )
        return

    if not _column_exists(
        db, "call_import_evaluations", "discover_new_metrics"
    ):
        db.execute(
            text(
                """
                ALTER TABLE call_import_evaluations
                ADD COLUMN discover_new_metrics BOOLEAN
                    NOT NULL DEFAULT FALSE
                """
            )
        )
        print(
            "Added call_import_evaluations.discover_new_metrics column"
        )
    else:
        print(
            "call_import_evaluations.discover_new_metrics already exists, "
            "skipping..."
        )

    if not _column_exists(
        db, "call_import_evaluations", "discovered_metric_aliases"
    ):
        db.execute(
            text(
                """
                ALTER TABLE call_import_evaluations
                ADD COLUMN discovered_metric_aliases JSONB
                    NOT NULL DEFAULT '{}'::jsonb
                """
            )
        )
        print(
            "Added call_import_evaluations.discovered_metric_aliases column"
        )
    else:
        print(
            "call_import_evaluations.discovered_metric_aliases already "
            "exists, skipping..."
        )

    db.commit()
    print("Top-level metric discovery columns are in place")


def downgrade(db: Session):
    if _column_exists(
        db, "call_import_evaluations", "discovered_metric_aliases"
    ):
        db.execute(
            text(
                "ALTER TABLE call_import_evaluations "
                "DROP COLUMN discovered_metric_aliases"
            )
        )
    if _column_exists(
        db, "call_import_evaluations", "discover_new_metrics"
    ):
        db.execute(
            text(
                "ALTER TABLE call_import_evaluations "
                "DROP COLUMN discover_new_metrics"
            )
        )
    db.commit()
