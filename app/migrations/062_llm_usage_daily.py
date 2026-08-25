"""Migration: LLM usage daily rollups for org-scoped Usage reporting."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add llm_usage_daily table for LLM token/call rollups"


def upgrade(db: Session):
    exists = db.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'llm_usage_daily'
            """
        )
    ).first()
    if exists:
        print("llm_usage_daily already exists, skipping 062")
        db.commit()
        return

    db.execute(
        text(
            """
            CREATE TABLE llm_usage_daily (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
                product_section VARCHAR(64) NOT NULL,
                model VARCHAR(255) NOT NULL,
                resource_id UUID,
                resource_type VARCHAR(64),
                usage_date DATE NOT NULL,
                prompt_tokens BIGINT NOT NULL DEFAULT 0,
                completion_tokens BIGINT NOT NULL DEFAULT 0,
                cache_read_tokens BIGINT NOT NULL DEFAULT 0,
                cache_creation_tokens BIGINT NOT NULL DEFAULT 0,
                reasoning_tokens BIGINT NOT NULL DEFAULT 0,
                call_count BIGINT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX ix_llm_usage_daily_org_date
            ON llm_usage_daily (organization_id, usage_date)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX ix_llm_usage_daily_org_workspace_date
            ON llm_usage_daily (organization_id, workspace_id, usage_date)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX ix_llm_usage_daily_org_resource_date
            ON llm_usage_daily (organization_id, resource_id, usage_date)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_llm_usage_daily_bucket
            ON llm_usage_daily (
                organization_id,
                COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
                product_section,
                model,
                COALESCE(resource_id, '00000000-0000-0000-0000-000000000000'::uuid),
                usage_date
            )
            """
        )
    )
    db.commit()
    print("Created llm_usage_daily table")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS llm_usage_daily"))
    db.commit()
