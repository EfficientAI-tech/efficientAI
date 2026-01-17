"""Add DEEPGRAM enum value to integrationplatform."""

from sqlalchemy import text

description = "Add DEEPGRAM to integrationplatform enum"


def upgrade(db):
    """Apply this migration."""
    # Add the new enum value only if it does not already exist
    db.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_enum e
                    JOIN pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'integrationplatform'
                      AND e.enumlabel = 'DEEPGRAM'
                ) THEN
                    ALTER TYPE integrationplatform ADD VALUE 'DEEPGRAM';
                END IF;
            END
            $$;
            """
        )
    )
    db.commit()

