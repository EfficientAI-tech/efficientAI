"""Add source column to call_recordings to separate playground vs webhook."""

from sqlalchemy import text

description = "Add source column to call_recordings"


def upgrade(db):
    """Apply this migration."""
    db.execute(
        text(
            """
            ALTER TABLE call_recordings
            ADD COLUMN source VARCHAR NOT NULL DEFAULT 'playground'
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_recordings_source
            ON call_recordings (source)
            """
        )
    )
    db.commit()


def downgrade(db):
    """Revert this migration."""
    db.execute(text("DROP INDEX IF EXISTS ix_call_recordings_source"))
    db.execute(text("ALTER TABLE call_recordings DROP COLUMN IF EXISTS source"))
    db.commit()

