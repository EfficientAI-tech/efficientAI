"""Daily evaluator-result rollups for the results dashboard."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add evaluator_result_daily for completed, failed, duration, and score by day"


def upgrade(db: Session):
    exists = db.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'evaluator_result_daily'
            """
        )
    ).first()
    if exists:
        print("evaluator_result_daily already exists, skipping 121")
        db.commit()
        return

    db.execute(
        text(
            """
            CREATE TABLE evaluator_result_daily (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                usage_date DATE NOT NULL,
                agent_id UUID,
                scenario_id UUID,
                is_live BOOLEAN NOT NULL DEFAULT false,
                completed BIGINT NOT NULL DEFAULT 0,
                failed BIGINT NOT NULL DEFAULT 0,
                duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
                duration_count BIGINT NOT NULL DEFAULT 0,
                score JSONB NOT NULL DEFAULT '{}',
                metric_ids JSONB NOT NULL DEFAULT '[]',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX ix_evaluator_result_daily_org_workspace_date
            ON evaluator_result_daily (organization_id, workspace_id, usage_date)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_evaluator_result_daily_bucket
            ON evaluator_result_daily (
                organization_id,
                workspace_id,
                usage_date,
                COALESCE(agent_id, '00000000-0000-0000-0000-000000000000'::uuid),
                COALESCE(scenario_id, '00000000-0000-0000-0000-000000000000'::uuid),
                is_live
            )
            """
        )
    )
    db.commit()
