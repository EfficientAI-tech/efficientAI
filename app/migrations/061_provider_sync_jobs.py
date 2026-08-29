"""Migration: add provider_sync_jobs tables for ElevenLabs migration workflow."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add provider sync job tables"


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
    if not _table_exists(db, "provider_sync_jobs"):
        db.execute(
            text(
                """
                CREATE TABLE provider_sync_jobs (
                    id UUID PRIMARY KEY,
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                    integration_id UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
                    provider_platform VARCHAR(64) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'queued',
                    phase VARCHAR(32) NOT NULL DEFAULT 'queued',
                    config JSON,
                    cursor_state JSON,
                    agents_synced INTEGER NOT NULL DEFAULT 0,
                    conversations_cataloged INTEGER NOT NULL DEFAULT 0,
                    conversations_enriched INTEGER NOT NULL DEFAULT 0,
                    errors_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    started_at TIMESTAMPTZ NULL,
                    completed_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )

    if not _table_exists(db, "provider_sync_job_errors"):
        db.execute(
            text(
                """
                CREATE TABLE provider_sync_job_errors (
                    id UUID PRIMARY KEY,
                    job_id UUID NOT NULL REFERENCES provider_sync_jobs(id) ON DELETE CASCADE,
                    provider_call_id VARCHAR(255) NULL,
                    provider_agent_id VARCHAR(255) NULL,
                    phase VARCHAR(32) NOT NULL,
                    error_message TEXT NOT NULL,
                    payload JSON,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )

    db.execute(text("CREATE INDEX IF NOT EXISTS ix_provider_sync_jobs_org_id ON provider_sync_jobs (organization_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_provider_sync_jobs_workspace_id ON provider_sync_jobs (workspace_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_provider_sync_jobs_integration_id ON provider_sync_jobs (integration_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_provider_sync_jobs_status ON provider_sync_jobs (status)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_provider_sync_jobs_phase ON provider_sync_jobs (phase)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_provider_sync_jobs_platform ON provider_sync_jobs (provider_platform)"))

    db.execute(text("CREATE INDEX IF NOT EXISTS ix_provider_sync_job_errors_job_id ON provider_sync_job_errors (job_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_provider_sync_job_errors_call_id ON provider_sync_job_errors (provider_call_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_provider_sync_job_errors_phase ON provider_sync_job_errors (phase)"))
    db.commit()
    print("Added provider sync job tables")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS provider_sync_job_errors"))
    db.execute(text("DROP TABLE IF EXISTS provider_sync_jobs"))
    db.commit()
