"""
Migration: Mark one active evaluator suite per agent for inbound routing.

Adds ``is_active`` to evaluator_suites and backfills one active row per
(workspace_id, agent_id) (newest suite wins when multiple exist).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add is_active flag on evaluator_suites for inbound suite selection"


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


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _table_exists(db, "evaluator_suites"):
        print("evaluator_suites table missing, skipping...")
        return

    if not _column_exists(db, "evaluator_suites", "is_active"):
        db.execute(
            text(
                """
                ALTER TABLE evaluator_suites
                ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
        )
        print("Added evaluator_suites.is_active")

    db.execute(text("UPDATE evaluator_suites SET is_active = FALSE"))

    rows = db.execute(
        text(
            """
            SELECT id, workspace_id, agent_id
            FROM evaluator_suites
            ORDER BY workspace_id, agent_id, created_at DESC
            """
        )
    ).fetchall()
    seen: set[tuple] = set()
    for row in rows:
        key = (row.workspace_id, row.agent_id)
        if key in seen:
            continue
        seen.add(key)
        db.execute(
            text("UPDATE evaluator_suites SET is_active = TRUE WHERE id = :id"),
            {"id": row.id},
        )
    print("Backfilled one active evaluator suite per agent")


def downgrade(db: Session):
    if _table_exists(db, "evaluator_suites") and _column_exists(
        db, "evaluator_suites", "is_active"
    ):
        db.execute(text("ALTER TABLE evaluator_suites DROP COLUMN is_active"))
        print("Dropped evaluator_suites.is_active")
