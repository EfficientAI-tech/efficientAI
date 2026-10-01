"""Add simulation_medium to personas (voice vs text chat profiles)."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "personas.simulation_medium voice|text"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE personas
                ADD COLUMN IF NOT EXISTS simulation_medium VARCHAR(16) NOT NULL DEFAULT 'voice'
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE personas
            SET simulation_medium = 'text'
            WHERE (tts_provider IS NULL OR TRIM(tts_provider) = '')
              AND simulation_medium = 'voice'
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("ALTER TABLE personas DROP COLUMN IF EXISTS simulation_medium"))
    db.commit()
