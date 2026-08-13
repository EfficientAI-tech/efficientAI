"""
Migration: last_updated_by_user_id on call imports and evaluations.

Supports surfacing who created / last modified a batch or evaluation run
via FK to users (email resolved at read time).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add last_updated_by_user_id to call_imports and call_import_evaluations"
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
    for table in ("call_imports", "call_import_evaluations"):
        if not _table_exists(db, table):
            print(f"{table} does not exist, skipping...")
            continue
        if _column_exists(db, table, "last_updated_by_user_id"):
            print(f"{table}.last_updated_by_user_id already exists, skipping...")
            continue
        db.execute(
            text(
                f"""
                ALTER TABLE {table}
                ADD COLUMN last_updated_by_user_id UUID NULL
                    REFERENCES users(id) ON DELETE SET NULL
                """
            )
        )
        print(f"Added {table}.last_updated_by_user_id")


def downgrade(db: Session):
    for table in ("call_import_evaluations", "call_imports"):
        if not _table_exists(db, table):
            continue
        if not _column_exists(db, table, "last_updated_by_user_id"):
            continue
        db.execute(
            text(f"ALTER TABLE {table} DROP COLUMN last_updated_by_user_id")
        )
        print(f"Dropped {table}.last_updated_by_user_id")
