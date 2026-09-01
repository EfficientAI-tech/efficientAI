"""
Migration: Extend evaluator-result cluster jobs with date and multi-scenario scope.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add since, until, and scenario_ids columns to evaluator_result_cluster_jobs."
)


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _column_exists(db, "evaluator_result_cluster_jobs", "since"):
        db.execute(
            text(
                """
                ALTER TABLE evaluator_result_cluster_jobs
                ADD COLUMN since TIMESTAMPTZ NULL
                """
            )
        )
        print("Added evaluator_result_cluster_jobs.since")

    if not _column_exists(db, "evaluator_result_cluster_jobs", "until"):
        db.execute(
            text(
                """
                ALTER TABLE evaluator_result_cluster_jobs
                ADD COLUMN until TIMESTAMPTZ NULL
                """
            )
        )
        print("Added evaluator_result_cluster_jobs.until")

    if not _column_exists(db, "evaluator_result_cluster_jobs", "scenario_ids"):
        db.execute(
            text(
                """
                ALTER TABLE evaluator_result_cluster_jobs
                ADD COLUMN scenario_ids JSONB NULL
                """
            )
        )
        print("Added evaluator_result_cluster_jobs.scenario_ids")


def downgrade(db: Session):
    if _column_exists(db, "evaluator_result_cluster_jobs", "scenario_ids"):
        db.execute(
            text("ALTER TABLE evaluator_result_cluster_jobs DROP COLUMN scenario_ids")
        )
    if _column_exists(db, "evaluator_result_cluster_jobs", "until"):
        db.execute(text("ALTER TABLE evaluator_result_cluster_jobs DROP COLUMN until"))
    if _column_exists(db, "evaluator_result_cluster_jobs", "since"):
        db.execute(text("ALTER TABLE evaluator_result_cluster_jobs DROP COLUMN since"))
    print("Dropped evaluator_result_cluster_jobs scope columns")
