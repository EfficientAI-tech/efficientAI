"""Add CARTESIA enum value to integrationplatform."""

from sqlalchemy import text

description = "Add CARTESIA to integrationplatform enum"


def upgrade(db):
    """Apply this migration."""
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
                      AND e.enumlabel = 'CARTESIA'
                ) THEN
                    ALTER TYPE integrationplatform ADD VALUE 'CARTESIA';
                END IF;
            END;
            $$;
            """
        )
    )
    db.commit()

