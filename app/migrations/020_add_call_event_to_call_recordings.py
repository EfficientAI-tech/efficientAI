"""Add call_event column to call_recordings."""

from sqlalchemy import text

description = "Add call_event column to call_recordings"


def upgrade(db):
    """Apply this migration."""
    db.execute(
        text(
            """
            ALTER TABLE call_recordings
            ADD COLUMN call_event VARCHAR NULL
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_recordings_call_event
            ON call_recordings (call_event)
            """
        )
    )
    db.commit()


def downgrade(db):
    """Revert this migration."""
    db.execute(
        text(
            """
            DROP INDEX IF EXISTS ix_call_recordings_call_event
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE call_recordings
            DROP COLUMN IF EXISTS call_event
            """
        )
    )
    db.commit()

