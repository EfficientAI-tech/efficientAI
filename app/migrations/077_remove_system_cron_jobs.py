"""Remove platform system cron rows; platform jobs use Celery Beat."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Delete is_system cron_jobs; platform scheduling moved to Celery Beat"


def upgrade(db: Session) -> None:
    result = db.execute(
        text("DELETE FROM cron_jobs WHERE is_system = true")
    )
    db.commit()
    print(f"Removed {result.rowcount} system cron job row(s)")


def downgrade(db: Session) -> None:
    # System jobs are re-seeded by re-running migration 075 logic if needed.
    print("Downgrade: re-run 075 upgrade to restore system cron jobs if required")
