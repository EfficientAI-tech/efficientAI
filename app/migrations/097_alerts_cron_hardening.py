"""Alert suppress flag, cron dispatch audit, alert metric indexes."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "alerts suppress_reopen_until_ok, cron dispatch audit, indexes"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE alerts
                ADD COLUMN IF NOT EXISTS suppress_reopen_until_ok BOOLEAN NOT NULL DEFAULT FALSE
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE cron_jobs
                ADD COLUMN IF NOT EXISTS last_dispatch_celery_task_id VARCHAR(255)
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE cron_jobs
                ADD COLUMN IF NOT EXISTS last_dispatch_status VARCHAR(32)
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE cron_jobs
                ADD COLUMN IF NOT EXISTS last_dispatch_error TEXT
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_evaluator_results_org_created_at
                ON evaluator_results (organization_id, created_at DESC)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_alert_history_alert_status
                ON alert_history (alert_id, status)
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP INDEX IF EXISTS ix_alert_history_alert_status"))
    db.execute(text("DROP INDEX IF EXISTS ix_evaluator_results_org_created_at"))
    db.execute(text("ALTER TABLE cron_jobs DROP COLUMN IF EXISTS last_dispatch_error"))
    db.execute(text("ALTER TABLE cron_jobs DROP COLUMN IF EXISTS last_dispatch_status"))
    db.execute(
        text("ALTER TABLE cron_jobs DROP COLUMN IF EXISTS last_dispatch_celery_task_id")
    )
    db.execute(text("ALTER TABLE alerts DROP COLUMN IF EXISTS suppress_reopen_until_ok"))
    db.commit()
