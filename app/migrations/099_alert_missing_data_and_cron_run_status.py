"""Alert silence (missing data as zero) and cron job last run status."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "alerts.alert_on_missing_data; cron_jobs last_run_status/error"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE alerts
                ADD COLUMN IF NOT EXISTS alert_on_missing_data BOOLEAN NOT NULL DEFAULT false
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE cron_jobs
                ADD COLUMN IF NOT EXISTS last_run_status VARCHAR(32)
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE cron_jobs
                ADD COLUMN IF NOT EXISTS last_run_error TEXT
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("ALTER TABLE cron_jobs DROP COLUMN IF EXISTS last_run_error"))
    db.execute(text("ALTER TABLE cron_jobs DROP COLUMN IF EXISTS last_run_status"))
    db.execute(text("ALTER TABLE alerts DROP COLUMN IF EXISTS alert_on_missing_data"))
    db.commit()
