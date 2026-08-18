"""Migration: async usage cost recompute job tracking."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add usage_cost_recompute_jobs table for async cost backfill/recompute"


def _table_exists(db: Session, table: str) -> bool:
    return (
        db.execute(
            text(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_name = :table_name
                """
            ),
            {"table_name": table},
        ).first()
        is not None
    )


def upgrade(db: Session) -> None:
    if _table_exists(db, "usage_cost_recompute_jobs"):
        print("usage_cost_recompute_jobs already exists, skipping...")
        return

    db.execute(
        text(
            """
            CREATE TABLE usage_cost_recompute_jobs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                model VARCHAR(255),
                usage_kind VARCHAR(16),
                start_date DATE,
                end_date DATE,
                updated_rows BIGINT NOT NULL DEFAULT 0,
                error_message TEXT,
                celery_task_id VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                completed_at TIMESTAMPTZ
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_usage_cost_recompute_jobs_organization_id
            ON usage_cost_recompute_jobs(organization_id)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_usage_cost_recompute_jobs_org_status
            ON usage_cost_recompute_jobs(organization_id, status)
            """
        )
    )
    print("Created usage_cost_recompute_jobs table")


def downgrade(db: Session) -> None:
    db.execute(text("DROP TABLE IF EXISTS usage_cost_recompute_jobs"))
