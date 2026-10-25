"""Harbor simulation runs (job-level) and trial columns on evaluator_results."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "simulation_runs table; evaluator_results simulation_run_id / trial / reward columns"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(text("""
            CREATE TABLE IF NOT EXISTS simulation_runs (
                id UUID PRIMARY KEY,
                run_id VARCHAR(6) NOT NULL UNIQUE,
                organization_id UUID NOT NULL REFERENCES organizations(id),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                name VARCHAR,
                scenario_ids JSON NOT NULL DEFAULT '[]',
                persona_ids JSON NOT NULL DEFAULT '[]',
                metric_ids JSON,
                n_attempts INTEGER NOT NULL DEFAULT 1,
                n_concurrent INTEGER NOT NULL DEFAULT 4,
                pass_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.7,
                production_llm_provider VARCHAR(64),
                production_llm_model VARCHAR(255),
                test_llm_provider VARCHAR(64),
                test_llm_model VARCHAR(255),
                status VARCHAR(20) NOT NULL DEFAULT 'queued',
                expected_trials INTEGER NOT NULL DEFAULT 0,
                completed_trials INTEGER NOT NULL DEFAULT 0,
                failed_trials INTEGER NOT NULL DEFAULT 0,
                summary JSON,
                error_message TEXT,
                harbor_job_name VARCHAR(255),
                artifacts_s3_key VARCHAR,
                celery_task_id VARCHAR,
                cancel_requested BOOLEAN NOT NULL DEFAULT false,
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                created_by VARCHAR
            )
            """))
    for column in ("organization_id", "workspace_id", "agent_id", "status"):
        db.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_simulation_runs_{column} "
                f"ON simulation_runs ({column})"
            )
        )

    db.execute(text("""
            ALTER TABLE evaluator_results
                ADD COLUMN IF NOT EXISTS simulation_run_id UUID
                    REFERENCES simulation_runs(id) ON DELETE CASCADE,
                ADD COLUMN IF NOT EXISTS harbor_trial_name VARCHAR(255),
                ADD COLUMN IF NOT EXISTS attempt_index INTEGER,
                ADD COLUMN IF NOT EXISTS reward DOUBLE PRECISION,
                ADD COLUMN IF NOT EXISTS passed BOOLEAN
            """))
    db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_evaluator_results_simulation_run_id
                ON evaluator_results (simulation_run_id)
            """))
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP INDEX IF EXISTS ix_evaluator_results_simulation_run_id"))
    db.execute(text("""
            ALTER TABLE evaluator_results
                DROP COLUMN IF EXISTS passed,
                DROP COLUMN IF EXISTS reward,
                DROP COLUMN IF EXISTS attempt_index,
                DROP COLUMN IF EXISTS harbor_trial_name,
                DROP COLUMN IF EXISTS simulation_run_id
            """))
    db.execute(text("DROP TABLE IF EXISTS simulation_runs"))
    db.commit()
