"""
Migration: Cached failure-cluster jobs scoped to evaluator-result filters.

Stores ``metric_clusters`` JSONB per workspace filter scope (agent / suite / scenario).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add evaluator_result_cluster_jobs table for scoped evaluation-results "
    "failure clustering."
)


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if _table_exists(db, "evaluator_result_cluster_jobs"):
        print("evaluator_result_cluster_jobs already exists, skipping...")
        return

    db.execute(
        text(
            """
            CREATE TABLE evaluator_result_cluster_jobs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                scope_key VARCHAR(512) NOT NULL,
                agent_id UUID NULL REFERENCES agents(id) ON DELETE SET NULL,
                suite_id UUID NULL REFERENCES evaluator_suites(id) ON DELETE SET NULL,
                scenario_id UUID NULL REFERENCES scenarios(id) ON DELETE SET NULL,
                metric_clusters JSONB NULL,
                celery_task_id VARCHAR NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (workspace_id, scope_key)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_evaluator_result_cluster_jobs_org
            ON evaluator_result_cluster_jobs (organization_id)
            """
        )
    )
    print("Created evaluator_result_cluster_jobs table")


def downgrade(db: Session):
    if not _table_exists(db, "evaluator_result_cluster_jobs"):
        print("evaluator_result_cluster_jobs missing, skipping...")
        return
    db.execute(text("DROP TABLE evaluator_result_cluster_jobs"))
    print("Dropped evaluator_result_cluster_jobs table")
