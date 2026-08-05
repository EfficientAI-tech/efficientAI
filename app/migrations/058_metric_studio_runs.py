"""Migration: Add Metrics Studio run tables."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add metric_studio_runs and metric_studio_run_results tables."


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
    if not _table_exists(db, "metric_studio_runs"):
        db.execute(
            text(
                """
                CREATE TABLE metric_studio_runs (
                    id UUID PRIMARY KEY,
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                    created_by_user_id UUID NULL REFERENCES users(id),
                    name VARCHAR(255) NULL,
                    selected_metric_ids JSON NOT NULL DEFAULT '[]',
                    selected_metric_groups JSON NULL,
                    transcript_source VARCHAR(20) NOT NULL DEFAULT 'diarised',
                    llm_provider VARCHAR(50) NULL,
                    llm_model VARCHAR(100) NULL,
                    llm_credential_id UUID NULL REFERENCES aiproviders(id) ON DELETE SET NULL,
                    llm_config JSON NULL,
                    metric_llm_overrides JSON NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    total_items INTEGER NOT NULL DEFAULT 0,
                    completed_items INTEGER NOT NULL DEFAULT 0,
                    failed_items INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT NULL,
                    started_at TIMESTAMPTZ NULL,
                    finished_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_metric_studio_runs_org ON metric_studio_runs (organization_id)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_metric_studio_runs_workspace ON metric_studio_runs (workspace_id)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_metric_studio_runs_status ON metric_studio_runs (status)"
            )
        )
        print("Created metric_studio_runs")

    if not _table_exists(db, "metric_studio_run_results"):
        db.execute(
            text(
                """
                CREATE TABLE metric_studio_run_results (
                    id UUID PRIMARY KEY,
                    run_id UUID NOT NULL REFERENCES metric_studio_runs(id) ON DELETE CASCADE,
                    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                    source_kind VARCHAR(40) NOT NULL,
                    source_ref VARCHAR(255) NOT NULL,
                    display_label VARCHAR(512) NULL,
                    source_metadata JSON NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    metric_scores JSON NOT NULL DEFAULT '{}',
                    error_message TEXT NULL,
                    celery_task_id VARCHAR(255) NULL,
                    started_at TIMESTAMPTZ NULL,
                    finished_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_metric_studio_run_results_run ON metric_studio_run_results (run_id)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_metric_studio_run_results_status ON metric_studio_run_results (status)"
            )
        )
        print("Created metric_studio_run_results")


def downgrade(db: Session):
    if _table_exists(db, "metric_studio_run_results"):
        db.execute(text("DROP TABLE metric_studio_run_results"))
    if _table_exists(db, "metric_studio_runs"):
        db.execute(text("DROP TABLE metric_studio_runs"))
