"""
Migration: Add is_active flag on workspaces for org-admin deactivation.

Inactive workspaces are fully locked for non-org-admin callers; org admins
retain access for inspection and reactivation.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add workspaces.is_active (default true) for org-admin deactivation."


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
    if not _column_exists(db, "workspaces", "is_active"):
        db.execute(
            text(
                """
                ALTER TABLE workspaces
                ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE
                """
            )
        )
        print("Added workspaces.is_active (boolean, default true)")


def downgrade(db: Session):
    if _column_exists(db, "workspaces", "is_active"):
        db.execute(text("ALTER TABLE workspaces DROP COLUMN is_active"))
        print("Dropped workspaces.is_active")
