"""Migration: Add llm_config JSON to evaluators and call_import_evaluations."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add llm_config JSON columns for user-tunable LLM generation parameters."
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
    if not _column_exists(db, "evaluators", "llm_config"):
        db.execute(text("ALTER TABLE evaluators ADD COLUMN llm_config JSON"))
        print("Added evaluators.llm_config")
    else:
        print("evaluators.llm_config already exists, skipping")

    if not _column_exists(db, "call_import_evaluations", "llm_config"):
        db.execute(
            text("ALTER TABLE call_import_evaluations ADD COLUMN llm_config JSON")
        )
        print("Added call_import_evaluations.llm_config")
    else:
        print("call_import_evaluations.llm_config already exists, skipping")


def downgrade(db: Session):
    if _column_exists(db, "evaluators", "llm_config"):
        db.execute(text("ALTER TABLE evaluators DROP COLUMN llm_config"))
        print("Dropped evaluators.llm_config")
    if _column_exists(db, "call_import_evaluations", "llm_config"):
        db.execute(
            text("ALTER TABLE call_import_evaluations DROP COLUMN llm_config")
        )
        print("Dropped call_import_evaluations.llm_config")
