"""
Migration: Move ``capture_rationale`` from child sub-metrics to their parent.

Hierarchical categorization metrics used to emit one rationale per child
(``Metric.capture_rationale`` set on each child boolean). The new model
emits a single rationale at the parent level instead, so the call-imports
table can render exactly one ``<Parent> - LLM Rationale`` column per
categorization metric (regardless of how many child labels exist).

This migration:
  1. For every parent metric (``selection_mode IS NOT NULL`` AND
     ``parent_metric_id IS NULL``) whose any enabled child has
     ``capture_rationale = TRUE``, set the parent's ``capture_rationale``
     to TRUE. Pre-existing parents that opted in via the new flow are
     unaffected (the OR keeps them on).
  2. For every child sub-metric (``parent_metric_id IS NOT NULL``), force
     ``capture_rationale = FALSE``. The LLM prompt builder + worker no
     longer read child-level rationale flags in hierarchical mode, so
     leaving them TRUE would create silent drift between the metric
     config and what the table actually shows.

Idempotent: safe to re-run. If the column isn't present yet (i.e. the
``030_metric_capture_rationale`` migration hasn't been applied), the
function is a no-op.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


description = (
    "Move capture_rationale from category sub-label children to their "
    "parent metric (one rationale per categorization, not per child)."
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
    if not _table_exists(db, "metrics"):
        print("metrics table does not exist; skipping parent rationale migration")
        return

    # Both columns are required for the migration to be meaningful.
    # ``capture_rationale`` is added by migration 030; ``parent_metric_id``
    # + ``selection_mode`` are added by 031_metric_hierarchy.
    if not _column_exists(db, "metrics", "capture_rationale"):
        print(
            "metrics.capture_rationale not present yet; "
            "skipping parent rationale migration"
        )
        return
    if not _column_exists(db, "metrics", "parent_metric_id"):
        print(
            "metrics.parent_metric_id not present yet; "
            "skipping parent rationale migration"
        )
        return
    if not _column_exists(db, "metrics", "selection_mode"):
        print(
            "metrics.selection_mode not present yet; "
            "skipping parent rationale migration"
        )
        return

    # Step 1: any parent whose any child currently has capture_rationale=true
    # gets capture_rationale=true on the parent too. We compute and update
    # in a single SQL statement so the migration is atomic per row.
    parents_updated = db.execute(
        text(
            """
            UPDATE metrics AS p
            SET capture_rationale = TRUE
            WHERE p.parent_metric_id IS NULL
              AND p.selection_mode IS NOT NULL
              AND p.capture_rationale = FALSE
              AND EXISTS (
                SELECT 1
                FROM metrics AS c
                WHERE c.parent_metric_id = p.id
                  AND c.capture_rationale = TRUE
              )
            """
        )
    ).rowcount
    print(
        f"Migrated capture_rationale onto {parents_updated} parent "
        "metric(s) from their children."
    )

    # Step 2: clear capture_rationale on every child sub-metric. Children
    # never emit their own rationale in hierarchical mode, so the worker
    # would silently drop any rationale key the LLM produces. Resetting
    # the flag keeps the stored config honest.
    children_cleared = db.execute(
        text(
            """
            UPDATE metrics
            SET capture_rationale = FALSE
            WHERE parent_metric_id IS NOT NULL
              AND capture_rationale = TRUE
            """
        )
    ).rowcount
    print(
        f"Cleared capture_rationale on {children_cleared} child sub-metric(s)."
    )

    db.commit()
    print("Parent rationale migration complete.")


def downgrade(db: Session):
    # This migration is data-only; there is no schema change to revert.
    # We deliberately do NOT attempt to push capture_rationale back down
    # to children because the original per-child distribution wasn't
    # preserved (the parent now carries a single OR'd flag).
    print(
        "Downgrade is a no-op — the per-child rationale distribution "
        "was lossy and cannot be reconstructed."
    )
