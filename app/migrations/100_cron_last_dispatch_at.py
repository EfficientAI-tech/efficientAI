"""Timestamp for cron dispatch failures so alert windows can exclude old pages."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "cron_jobs.last_dispatch_at"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE cron_jobs
                ADD COLUMN IF NOT EXISTS last_dispatch_at TIMESTAMPTZ
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("ALTER TABLE cron_jobs DROP COLUMN IF EXISTS last_dispatch_at"))
    db.commit()
