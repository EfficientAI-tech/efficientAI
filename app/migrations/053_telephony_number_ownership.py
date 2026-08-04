"""
Migration: Telephony number ownership flags and global inbound uniqueness.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add telephony number ownership columns and inbound DID uniqueness"


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


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = :column_name
            )
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


def upgrade(db: Session):
    if not _table_exists(db, "telephony_phone_numbers"):
        db.commit()
        return

    if not _column_exists(db, "telephony_phone_numbers", "inbound_enabled"):
        db.execute(
            text(
                """
                ALTER TABLE telephony_phone_numbers
                ADD COLUMN inbound_enabled BOOLEAN NOT NULL DEFAULT TRUE
                """
            )
        )

    if not _column_exists(db, "telephony_phone_numbers", "outbound_enabled"):
        db.execute(
            text(
                """
                ALTER TABLE telephony_phone_numbers
                ADD COLUMN outbound_enabled BOOLEAN NOT NULL DEFAULT TRUE
                """
            )
        )

    if not _column_exists(db, "telephony_phone_numbers", "source"):
        db.execute(
            text(
                """
                ALTER TABLE telephony_phone_numbers
                ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'imported'
                """
            )
        )

    db.execute(
        text(
            """
            ALTER TABLE telephony_phone_numbers
            ALTER COLUMN telephony_integration_id DROP NOT NULL
            """
        )
    )

    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_telephony_inbound_phone_global
            ON telephony_phone_numbers(phone_number)
            WHERE inbound_enabled = TRUE AND source <> 'platform_pool'
            """
        )
    )

    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "telephony_phone_numbers"):
        db.commit()
        return

    db.execute(text("DROP INDEX IF EXISTS uq_telephony_inbound_phone_global"))

    if _column_exists(db, "telephony_phone_numbers", "source"):
        db.execute(text("ALTER TABLE telephony_phone_numbers DROP COLUMN source"))
    if _column_exists(db, "telephony_phone_numbers", "outbound_enabled"):
        db.execute(text("ALTER TABLE telephony_phone_numbers DROP COLUMN outbound_enabled"))
    if _column_exists(db, "telephony_phone_numbers", "inbound_enabled"):
        db.execute(text("ALTER TABLE telephony_phone_numbers DROP COLUMN inbound_enabled"))

    db.commit()
