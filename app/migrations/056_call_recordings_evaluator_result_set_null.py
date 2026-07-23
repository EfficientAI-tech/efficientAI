"""
Migration: ON DELETE SET NULL for call_recordings.evaluator_result_id.

Allows deleting evaluator results without removing linked observability calls.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Set call_recordings.evaluator_result_id FK to ON DELETE SET NULL"


def _constraint_exists(db: Session, constraint_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.table_constraints
            WHERE constraint_name = :name
            """
        ),
        {"name": constraint_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if not _constraint_exists(db, "call_recordings_evaluator_result_id_fkey"):
        return

    db.execute(
        text(
            """
            ALTER TABLE call_recordings
            DROP CONSTRAINT call_recordings_evaluator_result_id_fkey
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE call_recordings
            ADD CONSTRAINT call_recordings_evaluator_result_id_fkey
            FOREIGN KEY (evaluator_result_id)
            REFERENCES evaluator_results(id)
            ON DELETE SET NULL
            """
        )
    )
    print("Updated call_recordings.evaluator_result_id FK to ON DELETE SET NULL")


def downgrade(db: Session):
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if not _constraint_exists(db, "call_recordings_evaluator_result_id_fkey"):
        return

    db.execute(
        text(
            """
            ALTER TABLE call_recordings
            DROP CONSTRAINT call_recordings_evaluator_result_id_fkey
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE call_recordings
            ADD CONSTRAINT call_recordings_evaluator_result_id_fkey
            FOREIGN KEY (evaluator_result_id)
            REFERENCES evaluator_results(id)
            """
        )
    )
