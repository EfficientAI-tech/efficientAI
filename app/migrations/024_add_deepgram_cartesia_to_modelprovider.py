"""Add DEEPGRAM and CARTESIA to modelprovider enum."""

from sqlalchemy import text

description = "Add DEEPGRAM and CARTESIA to modelprovider enum"


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
                    WHERE t.typname = 'modelprovider'
                      AND e.enumlabel = 'DEEPGRAM'
                ) THEN
                    ALTER TYPE modelprovider ADD VALUE 'DEEPGRAM';
                END IF;
            END;
            $$;
            """
        )
    )
    db.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_enum e
                    JOIN pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'modelprovider'
                      AND e.enumlabel = 'CARTESIA'
                ) THEN
                    ALTER TYPE modelprovider ADD VALUE 'CARTESIA';
                END IF;
            END;
            $$;
            """
        )
    )
    db.commit()


