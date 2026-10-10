"""Platform historical call imports: catalog columns, slices, ledger, dispatch indexes."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "platform_call_imports"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE call_imports
                ADD COLUMN IF NOT EXISTS voice_integration_id UUID
                    REFERENCES integrations(id) ON DELETE SET NULL,
                ADD COLUMN IF NOT EXISTS platform_filters JSONB NOT NULL DEFAULT '{}',
                ADD COLUMN IF NOT EXISTS window_start TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS window_end TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS window_timezone TEXT,
                ADD COLUMN IF NOT EXISTS discovery_status VARCHAR(32),
                ADD COLUMN IF NOT EXISTS max_calls INTEGER,
                ADD COLUMN IF NOT EXISTS next_row_index INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS skip_counts JSONB NOT NULL DEFAULT '{}',
                ADD COLUMN IF NOT EXISTS skip_samples JSONB NOT NULL DEFAULT '[]',
                ADD COLUMN IF NOT EXISTS paused_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS pause_reason TEXT
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_imports_voice_integration_id
                ON call_imports (voice_integration_id)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_imports_discovery_status
                ON call_imports (discovery_status)
                WHERE source_format = 'platform'
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS call_import_discovery_slices (
                call_import_id UUID NOT NULL REFERENCES call_imports(id) ON DELETE CASCADE,
                slice_id INTEGER NOT NULL,
                slice_start TIMESTAMPTZ NOT NULL,
                slice_end TIMESTAMPTZ NOT NULL,
                cursor TEXT,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                listed INTEGER NOT NULL DEFAULT 0,
                accepted INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (call_import_id, slice_id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS platform_conversation_ledger (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                provider VARCHAR(50) NOT NULL,
                conversation_id VARCHAR(255) NOT NULL,
                call_import_id UUID NOT NULL REFERENCES call_imports(id) ON DELETE CASCADE,
                row_id UUID NOT NULL,
                row_index INTEGER NOT NULL,
                state VARCHAR(32) NOT NULL DEFAULT 'reserved',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (workspace_id, provider, conversation_id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_platform_ledger_call_import_id
                ON platform_conversation_ledger (call_import_id)
            """
        )
    )
    if _table_exists(db, "call_import_rows"):
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_call_import_rows_pending_dispatch
                    ON call_import_rows (call_import_id, created_at)
                    WHERE status = 'pending' AND celery_task_id IS NULL
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_call_import_rows_import_status
                    ON call_import_rows (call_import_id, status)
                """
            )
        )
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS platform_conversation_ledger"))
    db.execute(text("DROP TABLE IF EXISTS call_import_discovery_slices"))
    db.execute(text("DROP INDEX IF EXISTS ix_call_imports_discovery_status"))
    db.execute(text("DROP INDEX IF EXISTS ix_call_imports_voice_integration_id"))
    db.execute(
        text(
            """
            ALTER TABLE call_imports
                DROP COLUMN IF EXISTS pause_reason,
                DROP COLUMN IF EXISTS paused_at,
                DROP COLUMN IF EXISTS skip_samples,
                DROP COLUMN IF EXISTS skip_counts,
                DROP COLUMN IF EXISTS next_row_index,
                DROP COLUMN IF EXISTS max_calls,
                DROP COLUMN IF EXISTS discovery_status,
                DROP COLUMN IF EXISTS window_timezone,
                DROP COLUMN IF EXISTS window_end,
                DROP COLUMN IF EXISTS window_start,
                DROP COLUMN IF EXISTS platform_filters,
                DROP COLUMN IF EXISTS voice_integration_id
            """
        )
    )
    if _table_exists(db, "call_import_rows"):
        db.execute(text("DROP INDEX IF EXISTS ix_call_import_rows_import_status"))
        db.execute(text("DROP INDEX IF EXISTS ix_call_import_rows_pending_dispatch"))
    db.commit()


def _table_exists(db: Session, name: str) -> bool:
    row = db.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :n"
        ),
        {"n": name},
    ).first()
    return row is not None
