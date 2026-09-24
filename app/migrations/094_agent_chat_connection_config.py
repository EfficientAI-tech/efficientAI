"""Add JSON config for chat connection types (customer API, messaging)."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Agent chat_connection_config JSONB"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE agents
                ADD COLUMN IF NOT EXISTS chat_connection_config JSONB
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("ALTER TABLE agents DROP COLUMN IF EXISTS chat_connection_config"))
    db.commit()
