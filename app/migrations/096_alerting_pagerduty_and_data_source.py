"""Add PagerDuty routing keys and alert metric data_source."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "alerts: notify_pagerduty_routing_keys, data_source"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE alerts
                ADD COLUMN IF NOT EXISTS notify_pagerduty_routing_keys JSONB
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE alerts
                ADD COLUMN IF NOT EXISTS data_source VARCHAR(32) NOT NULL DEFAULT 'evaluations'
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("ALTER TABLE alerts DROP COLUMN IF EXISTS data_source"))
    db.execute(text("ALTER TABLE alerts DROP COLUMN IF EXISTS notify_pagerduty_routing_keys"))
    db.commit()
