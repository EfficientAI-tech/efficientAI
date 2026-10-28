"""Store recording duration on call import rows at ingest."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add recording_duration_seconds to call_import_rows"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE call_import_rows
                ADD COLUMN IF NOT EXISTS recording_duration_seconds INTEGER
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE call_import_rows
                DROP COLUMN IF EXISTS recording_duration_seconds
            """
        )
    )
    db.commit()
