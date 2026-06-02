"""
Migration: Cached LLM-generated user insights on call_import_evaluations.

Adds a single nullable ``user_insights jsonb`` column on
``call_import_evaluations`` to cache map-reduce LLM-generated pattern
insights for the External Audit PDF section 03. Populated lazily by a
background Celery job triggered alongside TLDR generation.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add user_insights jsonb column on call_import_evaluations for "
    "caching LLM-generated user insight blocks."
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
    if _column_exists(db, "call_import_evaluations", "user_insights"):
        print("call_import_evaluations.user_insights already exists, skipping...")
        return

    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluations
            ADD COLUMN user_insights JSONB NULL
            """
        )
    )
    print("Added call_import_evaluations.user_insights (nullable jsonb)")


def downgrade(db: Session):
    if not _column_exists(db, "call_import_evaluations", "user_insights"):
        print("call_import_evaluations.user_insights missing, skipping...")
        return
    db.execute(
        text("ALTER TABLE call_import_evaluations DROP COLUMN user_insights")
    )
    print("Dropped call_import_evaluations.user_insights")
