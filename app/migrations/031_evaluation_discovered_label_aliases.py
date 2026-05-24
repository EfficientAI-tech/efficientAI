"""
Migration: Persist LLM-discovered label merges at the evaluation level.

Adds ``call_import_evaluations.discovered_label_aliases`` — a JSONB map
shaped like::

    { "<parent_metric_id>": { "<from_slug>": "<to_slug>", ... } }

Whenever a user merges one LLM-discovered candidate into another via
``POST /evaluations/{eval_id}/discovered-labels/merge``, we record the
``from -> to`` redirect here in addition to rewriting the per-row
``metric_scores``. The redirect map is consulted by:

  * ``_get_running_discovered_labels`` so any leftover ``from_key``
    occurrences in still-completing rows are folded into the canonical
    target instead of resurrecting the merged-out candidate in the
    Discovered Labels panel.
  * ``_build_flow_graph`` so flow chart nodes/edges respect the merge.
  * The worker, which walks the alias map after computing each row's
    ``discovered_labels`` / ``sequence`` so newly-finished rows can't
    re-introduce the merged-away slug.

Idempotent: column is only added if it is not already present.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add discovered_label_aliases JSONB to call_import_evaluations for "
    "persistent LLM-discovered-label merges"
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
        # Older deploys may not have the evaluations table yet — earlier
        # migrations create it. Skip silently in that case.
        print(
            "Skipping 031: call_import_evaluations table is not present yet"
        )
        return

    if not _column_exists(
        db, "call_import_evaluations", "discovered_label_aliases"
    ):
        db.execute(
            text(
                """
                ALTER TABLE call_import_evaluations
                ADD COLUMN discovered_label_aliases JSONB
                    NOT NULL DEFAULT '{}'::jsonb
                """
            )
        )
        print(
            "Added call_import_evaluations.discovered_label_aliases column"
        )

    db.commit()


def downgrade(db: Session):
    if _column_exists(
        db, "call_import_evaluations", "discovered_label_aliases"
    ):
        db.execute(
            text(
                "ALTER TABLE call_import_evaluations "
                "DROP COLUMN discovered_label_aliases"
            )
        )
    db.commit()
