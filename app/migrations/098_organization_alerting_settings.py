"""Per-organization alerting integration sync settings."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "organizations.alerting_settings JSON for notification lifecycle sync"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE organizations
                ADD COLUMN IF NOT EXISTS alerting_settings JSONB
            """
        )
    )


def downgrade(db: Session):
    db.execute(text("ALTER TABLE organizations DROP COLUMN IF EXISTS alerting_settings"))
