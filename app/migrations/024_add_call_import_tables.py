"""
Migration: Add call_imports and call_import_rows tables.

These power the CSV-driven call-import feature where users upload a CSV of
(CallID, Recording URL, Transcript) and a Celery worker fetches each recording
from a third-party voice provider (Exotel) into S3.

The two tables are intentionally kept separate from CallRecording /
ManualTranscription / EvaluatorResult so imports stay isolated from the
existing observability and evaluation flows.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add call_imports and call_import_rows tables for CSV-driven call recording imports"


def _table_exists(db: Session, table_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    )
    return bool(result.scalar())


def upgrade(db: Session):
    """Create call_imports and call_import_rows tables with their indexes."""

    if not _table_exists(db, "call_imports"):
        db.execute(
            text(
                """
                CREATE TABLE call_imports (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    created_by_user_id UUID REFERENCES users(id),
                    provider VARCHAR(50) NOT NULL DEFAULT 'exotel',
                    original_filename VARCHAR(512),
                    total_rows INTEGER NOT NULL DEFAULT 0,
                    completed_rows INTEGER NOT NULL DEFAULT 0,
                    failed_rows INTEGER NOT NULL DEFAULT 0,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text("CREATE INDEX ix_call_imports_organization_id ON call_imports(organization_id)")
        )
        db.execute(
            text("CREATE INDEX ix_call_imports_status ON call_imports(status)")
        )
        db.execute(
            text(
                "CREATE INDEX ix_call_imports_org_created_at "
                "ON call_imports(organization_id, created_at DESC)"
            )
        )
        print("Created call_imports table")
    else:
        print("call_imports table already exists, skipping...")

    if not _table_exists(db, "call_import_rows"):
        db.execute(
            text(
                """
                CREATE TABLE call_import_rows (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    call_import_id UUID NOT NULL REFERENCES call_imports(id) ON DELETE CASCADE,
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    row_index INTEGER NOT NULL,
                    external_call_id VARCHAR(255) NOT NULL,
                    recording_url TEXT NOT NULL,
                    transcript TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    recording_s3_key VARCHAR(1024),
                    recording_content_type VARCHAR(128),
                    recording_size_bytes INTEGER,
                    error_message TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    celery_task_id VARCHAR(255),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    CONSTRAINT uq_call_import_row_index UNIQUE (call_import_id, row_index)
                )
                """
            )
        )
        db.execute(
            text("CREATE INDEX ix_call_import_rows_call_import_id ON call_import_rows(call_import_id)")
        )
        db.execute(
            text("CREATE INDEX ix_call_import_rows_organization_id ON call_import_rows(organization_id)")
        )
        db.execute(
            text("CREATE INDEX ix_call_import_rows_status ON call_import_rows(status)")
        )
        db.execute(
            text(
                "CREATE INDEX ix_call_import_rows_external_call_id "
                "ON call_import_rows(external_call_id)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_call_import_rows_org_status "
                "ON call_import_rows(organization_id, status)"
            )
        )
        print("Created call_import_rows table")
    else:
        print("call_import_rows table already exists, skipping...")

    db.commit()
    print("Successfully created call import tables")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS call_import_rows"))
    db.execute(text("DROP TABLE IF EXISTS call_imports"))
    db.commit()
