"""Migration: Add workspace-level report branding metadata."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add workspaces.report_branding JSON metadata for PDF report branding."


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
    if not _column_exists(db, "workspaces", "report_branding"):
        db.execute(text("ALTER TABLE workspaces ADD COLUMN report_branding JSONB"))
        print("Added workspaces.report_branding")
    else:
        print("workspaces.report_branding already exists, skipping")


def downgrade(db: Session):
    if _column_exists(db, "workspaces", "report_branding"):
        db.execute(text("ALTER TABLE workspaces DROP COLUMN report_branding"))
        print("Dropped workspaces.report_branding")
    else:
        print("workspaces.report_branding does not exist, skipping")
