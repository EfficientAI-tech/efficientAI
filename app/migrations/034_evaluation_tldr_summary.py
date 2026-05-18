"""
Migration: Cached TLDR summary on call_import_evaluations.

Adds a single nullable ``tldr_summary jsonb`` column on
``call_import_evaluations`` to cache the LLM-generated narrative + bullet
patterns rendered above the Visualizations charts. The column is
populated lazily by ``POST /evaluations/{eval_id}/insights`` (and only
regenerated on explicit user action) so the page never auto-burns LLM
tokens. Rendered shape::

    {
        "narrative": "<2-4 sentence summary>",
        "patterns": ["<bullet 1>", "<bullet 2>", ...],
        "generated_at": "<isoformat utc>",
        "generated_at_completed_rows": <int>,
        "provider": "<provider value, e.g. openai>",
        "model": "<model name, e.g. gpt-4o>"
    }

Idempotent: re-running the migration is a no-op once the column
exists.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add tldr_summary jsonb column on call_import_evaluations for "
    "caching LLM-generated narrative summaries (Visualizations tab)."
)


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if _column_exists(db, "call_import_evaluations", "tldr_summary"):
        print("call_import_evaluations.tldr_summary already exists, skipping...")
        return

    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluations
            ADD COLUMN tldr_summary JSONB NULL
            """
        )
    )
    print("Added call_import_evaluations.tldr_summary (nullable jsonb)")


def downgrade(db: Session):
    if not _column_exists(db, "call_import_evaluations", "tldr_summary"):
        print("call_import_evaluations.tldr_summary missing, skipping...")
        return
    db.execute(
        text("ALTER TABLE call_import_evaluations DROP COLUMN tldr_summary")
    )
    print("Dropped call_import_evaluations.tldr_summary")
