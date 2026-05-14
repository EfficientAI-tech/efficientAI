"""
Migration: Hierarchical sub-metrics + flow visualization data.

Adds:
  * ``metrics.parent_metric_id`` - self-referential FK so a "category"
    metric can own N child sub-metric labels. ``ON DELETE CASCADE``
    so deleting a parent removes its children.
  * ``metrics.selection_mode`` - VARCHAR(20) on parent rows only.
    ``single_choice`` (LLM picks exactly one child as true) or
    ``multi_label`` (each child evaluated independently with the LLM
    instructed to maintain logical consistency).
  * ``call_import_evaluations.selected_metric_groups`` - JSON mapping
    of ``parent_id -> [child_ids]`` so the worker / UI can reconstruct
    the parent/child grouping (including partial selections) without
    re-querying the user's original payload.

Idempotent: every step checks for prior existence before applying.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add parent_metric_id + selection_mode to metrics for hierarchical "
    "sub-metrics, and selected_metric_groups to call_import_evaluations"
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


def _index_exists(db: Session, name: str) -> bool:
    row = db.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :n"),
        {"n": name},
    ).first()
    return row is not None


def upgrade(db: Session):
    # --- metrics.parent_metric_id ---
    if not _column_exists(db, "metrics", "parent_metric_id"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN parent_metric_id UUID NULL
                    REFERENCES metrics(id) ON DELETE CASCADE
                """
            )
        )
        print("Added metrics.parent_metric_id")
    else:
        print("metrics.parent_metric_id already exists, skipping...")

    if not _index_exists(db, "ix_metrics_parent_metric_id"):
        db.execute(
            text(
                "CREATE INDEX ix_metrics_parent_metric_id "
                "ON metrics(parent_metric_id)"
            )
        )
        print("Created index ix_metrics_parent_metric_id")

    # --- metrics.selection_mode ---
    if not _column_exists(db, "metrics", "selection_mode"):
        db.execute(
            text(
                "ALTER TABLE metrics ADD COLUMN selection_mode VARCHAR(20) NULL"
            )
        )
        print("Added metrics.selection_mode")
    else:
        print("metrics.selection_mode already exists, skipping...")

    # --- call_import_evaluations.selected_metric_groups ---
    if not _column_exists(
        db, "call_import_evaluations", "selected_metric_groups"
    ):
        db.execute(
            text(
                """
                ALTER TABLE call_import_evaluations
                ADD COLUMN selected_metric_groups JSONB NULL
                """
            )
        )
        print("Added call_import_evaluations.selected_metric_groups")
    else:
        print(
            "call_import_evaluations.selected_metric_groups already exists, "
            "skipping..."
        )

    db.commit()
    print("Metric hierarchy schema is in place")


def downgrade(db: Session):
    db.execute(
        text(
            "ALTER TABLE call_import_evaluations "
            "DROP COLUMN IF EXISTS selected_metric_groups"
        )
    )
    db.execute(text("DROP INDEX IF EXISTS ix_metrics_parent_metric_id"))
    db.execute(
        text("ALTER TABLE metrics DROP COLUMN IF EXISTS selection_mode")
    )
    db.execute(
        text("ALTER TABLE metrics DROP COLUMN IF EXISTS parent_metric_id")
    )
    db.commit()
