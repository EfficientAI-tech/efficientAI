"""Background evaluation export jobs and their blob-storage parts."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add call_import_evaluation_exports for async evaluation downloads"
MIGRATION_SCOPE = "catalog"


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if _table_exists(db, "call_import_evaluation_exports"):
        print("call_import_evaluation_exports already exists, skipping")
        db.commit()
        return

    db.execute(
        text(
            """
            CREATE TABLE call_import_evaluation_exports (
                id UUID PRIMARY KEY,
                evaluation_id UUID NOT NULL
                    REFERENCES call_import_evaluations(id) ON DELETE CASCADE,
                call_import_id UUID NOT NULL
                    REFERENCES call_imports(id) ON DELETE CASCADE,
                organization_id UUID NOT NULL REFERENCES organizations(id),
                workspace_id UUID NOT NULL
                    REFERENCES workspaces(id) ON DELETE RESTRICT,
                format VARCHAR(8) NOT NULL DEFAULT 'csv',
                include_transcripts BOOLEAN NOT NULL DEFAULT FALSE,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                error_message TEXT,
                parts JSONB NOT NULL DEFAULT '[]'::jsonb,
                claim_token VARCHAR(36),
                heartbeat_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_import_evaluation_exports_evaluation_id
            ON call_import_evaluation_exports (evaluation_id)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_import_evaluation_exports_call_import_id
            ON call_import_evaluation_exports (call_import_id)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_import_evaluation_exports_organization_id
            ON call_import_evaluation_exports (organization_id)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_import_evaluation_exports_workspace_id
            ON call_import_evaluation_exports (workspace_id)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_import_evaluation_exports_status
            ON call_import_evaluation_exports (status)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_call_import_evaluation_exports_active
            ON call_import_evaluation_exports (evaluation_id)
            WHERE status IN ('pending', 'running')
            """
        )
    )
    print("Created call_import_evaluation_exports")
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS call_import_evaluation_exports"))
    db.commit()
