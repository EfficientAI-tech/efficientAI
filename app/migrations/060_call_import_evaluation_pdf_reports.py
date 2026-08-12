"""Migration: stored PDF reports for call import evaluations."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add call_import_evaluation_pdf_reports for S3-stored evaluation PDFs"


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
    if _table_exists(db, "call_import_evaluation_pdf_reports"):
        print("call_import_evaluation_pdf_reports already exists, skipping")
        db.commit()
        return

    db.execute(
        text(
            """
            CREATE TABLE call_import_evaluation_pdf_reports (
                id UUID PRIMARY KEY,
                evaluation_id UUID NOT NULL REFERENCES call_import_evaluations(id) ON DELETE CASCADE,
                call_import_id UUID NOT NULL REFERENCES call_imports(id) ON DELETE CASCADE,
                organization_id UUID NOT NULL REFERENCES organizations(id),
                workspace_id UUID NOT NULL REFERENCES workspaces(id),
                snapshot_id UUID REFERENCES call_import_evaluation_report_snapshots(id) ON DELETE SET NULL,
                vendor_name VARCHAR(120) NOT NULL,
                report_type VARCHAR(20) NOT NULL DEFAULT 'external',
                filename VARCHAR(255),
                s3_key VARCHAR(512),
                report_config JSONB NOT NULL DEFAULT '{}'::jsonb,
                cache_fingerprint VARCHAR(64),
                created_by TEXT,
                created_by_user_id UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_import_eval_pdf_reports_eval
            ON call_import_evaluation_pdf_reports (evaluation_id, created_at DESC)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            uq_call_import_eval_pdf_reports_eval_cache_fp
            ON call_import_evaluation_pdf_reports (evaluation_id, cache_fingerprint)
            WHERE cache_fingerprint IS NOT NULL
            """
        )
    )
    print("Created call_import_evaluation_pdf_reports")
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS call_import_evaluation_pdf_reports"))
    db.commit()
