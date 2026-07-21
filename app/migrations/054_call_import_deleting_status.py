"""
Migration: Add ``deleting`` to the ``callimportstatus`` Postgres enum.

Supports async whole-batch call-import deletion: the API flips a batch
to ``deleting`` and returns 202 while a worker tears down rows + S3.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add 'deleting' to the callimportstatus Postgres enum for async "
    "whole-batch call-import deletion."
)


def _enum_type_exists(db: Session) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM pg_type
            WHERE typname = 'callimportstatus'
            """
        )
    ).first()
    return row is not None


def _enum_has_value(db: Session, value: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM pg_enum e
            JOIN pg_type t ON t.oid = e.enumtypid
            WHERE t.typname = 'callimportstatus'
              AND e.enumlabel = :value
            """
        ),
        {"value": value},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _enum_type_exists(db):
        print(
            "callimportstatus enum type does not exist; column is likely "
            "VARCHAR-backed, nothing to migrate."
        )
        return

    if _enum_has_value(db, "deleting"):
        print("callimportstatus already has value 'deleting', skipping...")
        return

    db.execute(
        text("ALTER TYPE callimportstatus ADD VALUE IF NOT EXISTS 'deleting'")
    )
    db.commit()
    print("Added 'deleting' to callimportstatus enum")


def downgrade(db: Session):
    print(
        "Downgrade for enum additions is a no-op; Postgres does not "
        "support removing individual enum values safely."
    )
