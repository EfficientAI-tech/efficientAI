"""Migration: computed metric scoring_method and call-import speaker aliases."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "metric_scoring_method_and_call_import_speaker_aliases"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE metrics
                ADD COLUMN IF NOT EXISTS scoring_method VARCHAR(32) NOT NULL DEFAULT 'llm'
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE call_imports
                ADD COLUMN IF NOT EXISTS speaker_aliases JSONB NULL
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE call_imports
                DROP COLUMN IF EXISTS speaker_aliases
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE metrics
                DROP COLUMN IF EXISTS scoring_method
            """
        )
    )
    db.commit()
