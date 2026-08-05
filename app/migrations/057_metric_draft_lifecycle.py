"""Migration: Add metric draft lifecycle columns."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add lifecycle, promoted_from_draft_at, studio_notes to metrics."


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
    if not _column_exists(db, "metrics", "lifecycle"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN lifecycle VARCHAR(20) NOT NULL DEFAULT 'active'
                """
            )
        )
        print("Added metrics.lifecycle")

    if not _column_exists(db, "metrics", "promoted_from_draft_at"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN promoted_from_draft_at TIMESTAMPTZ NULL
                """
            )
        )
        print("Added metrics.promoted_from_draft_at")

    if not _column_exists(db, "metrics", "studio_notes"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN studio_notes TEXT NULL
                """
            )
        )
        print("Added metrics.studio_notes")


def downgrade(db: Session):
    if _column_exists(db, "metrics", "studio_notes"):
        db.execute(text("ALTER TABLE metrics DROP COLUMN studio_notes"))
    if _column_exists(db, "metrics", "promoted_from_draft_at"):
        db.execute(text("ALTER TABLE metrics DROP COLUMN promoted_from_draft_at"))
    if _column_exists(db, "metrics", "lifecycle"):
        db.execute(text("ALTER TABLE metrics DROP COLUMN lifecycle"))
