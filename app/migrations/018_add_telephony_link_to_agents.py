"""
Migration: Link agents to telephony phone numbers.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add telephony_phone_number_id FK on agents for provider-linked phone call routing"


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


def _constraint_exists(db: Session, table_name: str, constraint_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name = :table_name
                  AND constraint_name = :constraint_name
            )
            """
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    )
    return bool(result.scalar())


def upgrade(db: Session):
    if _table_exists(db, "agents") and not _column_exists(db, "agents", "telephony_phone_number_id"):
        db.execute(text("ALTER TABLE agents ADD COLUMN telephony_phone_number_id UUID"))

    if (
        _table_exists(db, "agents")
        and _table_exists(db, "telephony_phone_numbers")
        and _column_exists(db, "agents", "telephony_phone_number_id")
        and not _constraint_exists(db, "agents", "fk_agents_telephony_phone_number_id")
    ):
        db.execute(
            text(
                """
                ALTER TABLE agents
                ADD CONSTRAINT fk_agents_telephony_phone_number_id
                FOREIGN KEY (telephony_phone_number_id)
                REFERENCES telephony_phone_numbers(id)
                ON DELETE SET NULL
                """
            )
        )

    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_agents_telephony_phone_number_id
            ON agents(telephony_phone_number_id)
            """
        )
    )

    db.commit()


def downgrade(db: Session):
    if _table_exists(db, "agents"):
        db.execute(text("DROP INDEX IF EXISTS ix_agents_telephony_phone_number_id"))
        db.execute(text("ALTER TABLE agents DROP CONSTRAINT IF EXISTS fk_agents_telephony_phone_number_id"))
        if _column_exists(db, "agents", "telephony_phone_number_id"):
            db.execute(text("ALTER TABLE agents DROP COLUMN telephony_phone_number_id"))

    db.commit()
