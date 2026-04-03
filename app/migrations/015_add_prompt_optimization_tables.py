"""
Migration: Add GEPA prompt optimization tables.

Creates prompt_optimization_runs and prompt_optimization_candidates
for the enterprise self-improving voice agents feature.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add prompt_optimization_runs and prompt_optimization_candidates tables"


def upgrade(db: Session):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS prompt_optimization_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id),
            agent_id UUID NOT NULL REFERENCES agents(id),
            evaluator_id UUID REFERENCES evaluators(id),
            voice_bundle_id UUID REFERENCES voicebundles(id),

            seed_prompt TEXT NOT NULL,
            best_prompt TEXT,
            best_score DOUBLE PRECISION,

            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            config JSONB,
            reflection_trace JSONB,
            metric_history JSONB,

            num_iterations INTEGER,
            num_metric_calls INTEGER,

            celery_task_id VARCHAR,
            error_message TEXT,

            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            created_by VARCHAR
        )
    """))

    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_prompt_optimization_runs_org
            ON prompt_optimization_runs (organization_id)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_prompt_optimization_runs_agent
            ON prompt_optimization_runs (agent_id)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_prompt_optimization_runs_celery
            ON prompt_optimization_runs (celery_task_id)
    """))

    db.execute(text("""
        CREATE TABLE IF NOT EXISTS prompt_optimization_candidates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            optimization_run_id UUID NOT NULL
                REFERENCES prompt_optimization_runs(id) ON DELETE CASCADE,

            prompt_text TEXT NOT NULL,
            score DOUBLE PRECISION,
            metric_breakdown JSONB,
            reflection_summary TEXT,

            parent_candidate_id UUID REFERENCES prompt_optimization_candidates(id),

            is_accepted BOOLEAN NOT NULL DEFAULT FALSE,
            pushed_to_provider_at TIMESTAMPTZ,

            created_at TIMESTAMPTZ DEFAULT now()
        )
    """))

    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_prompt_optimization_candidates_run
            ON prompt_optimization_candidates (optimization_run_id)
    """))

    db.commit()
    print("Created prompt_optimization_runs and prompt_optimization_candidates tables")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS prompt_optimization_candidates CASCADE"))
    db.execute(text("DROP TABLE IF EXISTS prompt_optimization_runs CASCADE"))
    db.commit()
    print("Dropped prompt optimization tables")
