"""
Migration: Cached period delta explanations on call_import_evaluations.

Adds a nullable ``period_delta_explanations jsonb`` column to cache
LLM-generated "why the delta happened" text keyed by baseline evaluation
id and completed row counts.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add period_delta_explanations jsonb column on call_import_evaluations "
    "for caching week-over-week delta explanations."
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
    if _column_exists(db, "call_import_evaluations", "period_delta_explanations"):
        print(
            "call_import_evaluations.period_delta_explanations already exists, skipping..."
        )
        return

    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluations
            ADD COLUMN period_delta_explanations JSONB NULL
            """
        )
    )
    print("Added call_import_evaluations.period_delta_explanations (nullable jsonb)")


def downgrade(db: Session):
    if not _column_exists(db, "call_import_evaluations", "period_delta_explanations"):
        print(
            "call_import_evaluations.period_delta_explanations missing, skipping..."
        )
        return
    db.execute(
        text(
            "ALTER TABLE call_import_evaluations DROP COLUMN period_delta_explanations"
        )
    )
    print("Dropped call_import_evaluations.period_delta_explanations")
