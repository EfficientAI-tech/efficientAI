"""
Migration: Add tts_report_jobs table for async PDF report generation.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add tts_report_jobs table for Voice Playground report generation"


def upgrade(db: Session):
    result = db.execute(
        text(
            """
        SELECT table_name FROM information_schema.tables
        WHERE table_name = 'tts_report_jobs'
        """
        )
    )

    if result.fetchone() is not None:
        print("tts_report_jobs table already exists, skipping...")
        return

    db.execute(
        text(
            """
        CREATE TABLE tts_report_jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id),
            comparison_id UUID NOT NULL REFERENCES tts_comparisons(id) ON DELETE CASCADE,
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            format VARCHAR(20) NOT NULL DEFAULT 'pdf',
            filename VARCHAR(255),
            s3_key VARCHAR(512),
            error_message TEXT,
            celery_task_id VARCHAR,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            created_by VARCHAR
        )
        """
        )
    )

    db.execute(
        text(
            """
        CREATE INDEX IF NOT EXISTS ix_tts_report_jobs_organization_id
        ON tts_report_jobs(organization_id)
        """
        )
    )
    db.execute(
        text(
            """
        CREATE INDEX IF NOT EXISTS ix_tts_report_jobs_comparison_id
        ON tts_report_jobs(comparison_id)
        """
        )
    )
    db.execute(
        text(
            """
        CREATE INDEX IF NOT EXISTS ix_tts_report_jobs_celery_task_id
        ON tts_report_jobs(celery_task_id)
        """
        )
    )

    db.commit()
    print("Created tts_report_jobs table")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS tts_report_jobs"))
    db.commit()
