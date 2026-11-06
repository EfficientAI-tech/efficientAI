"""Expected tool calls on scenarios (tool-use checks in simulation runs)."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "scenarios.expected_tool_calls JSON column"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(text("""
            ALTER TABLE scenarios
                ADD COLUMN IF NOT EXISTS expected_tool_calls JSON
            """))
    db.commit()


def downgrade(db: Session):
    db.execute(text("""
            ALTER TABLE scenarios
                DROP COLUMN IF EXISTS expected_tool_calls
            """))
    db.commit()
