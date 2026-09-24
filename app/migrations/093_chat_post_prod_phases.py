"""Chat post-prod: eval mode on agents, content_modality on call imports."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "chat_eval_mode on agents; content_modality on call_imports"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE agents
                ADD COLUMN IF NOT EXISTS chat_eval_mode VARCHAR(32)
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE call_imports
                ADD COLUMN IF NOT EXISTS content_modality VARCHAR(16)
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("ALTER TABLE call_imports DROP COLUMN IF EXISTS content_modality"))
    db.execute(text("ALTER TABLE agents DROP COLUMN IF EXISTS chat_eval_mode"))
    db.commit()
