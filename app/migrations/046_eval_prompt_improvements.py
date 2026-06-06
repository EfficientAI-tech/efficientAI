"""Migration: Cache prompt improvement suggestions on call import evaluations."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add call_import_evaluations.prompt_improvements JSON column."


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
    if not _column_exists(db, "call_import_evaluations", "prompt_improvements"):
        db.execute(
            text("ALTER TABLE call_import_evaluations ADD COLUMN prompt_improvements JSON")
        )
        print("Added call_import_evaluations.prompt_improvements")
    else:
        print("call_import_evaluations.prompt_improvements already exists, skipping")


def downgrade(db: Session):
    if _column_exists(db, "call_import_evaluations", "prompt_improvements"):
        db.execute(
            text("ALTER TABLE call_import_evaluations DROP COLUMN prompt_improvements")
        )
        print("Dropped call_import_evaluations.prompt_improvements")
