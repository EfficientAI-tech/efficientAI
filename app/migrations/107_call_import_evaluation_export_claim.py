"""Add the export claim columns when 106 created the table without them."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add claim_token and heartbeat_at to call_import_evaluation_exports"
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
    if not _table_exists(db, "call_import_evaluation_exports"):
        db.commit()
        return
    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluation_exports
                ADD COLUMN IF NOT EXISTS claim_token VARCHAR(36),
                ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ
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
    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "call_import_evaluation_exports"):
        db.commit()
        return
    db.execute(
        text(
            """
            DROP INDEX IF EXISTS uq_call_import_evaluation_exports_active
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluation_exports
                DROP COLUMN IF EXISTS heartbeat_at,
                DROP COLUMN IF EXISTS claim_token
            """
        )
    )
    db.commit()
