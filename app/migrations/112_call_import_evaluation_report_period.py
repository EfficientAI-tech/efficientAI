"""Persist ISO-week report period on evaluations for fast baseline lookup."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Report period columns on call_import_evaluations"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluations
                ADD COLUMN IF NOT EXISTS report_period_start DATE,
                ADD COLUMN IF NOT EXISTS report_period_end DATE,
                ADD COLUMN IF NOT EXISTS report_period_label VARCHAR(64),
                ADD COLUMN IF NOT EXISTS report_period_display VARCHAR(128),
                ADD COLUMN IF NOT EXISTS report_period_at_count INTEGER
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_import_evaluations_report_period_start
                ON call_import_evaluations (report_period_start)
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP INDEX IF EXISTS ix_call_import_evaluations_report_period_start"))
    db.execute(
        text(
            """
            ALTER TABLE call_import_evaluations
                DROP COLUMN IF EXISTS report_period_at_count,
                DROP COLUMN IF EXISTS report_period_display,
                DROP COLUMN IF EXISTS report_period_label,
                DROP COLUMN IF EXISTS report_period_end,
                DROP COLUMN IF EXISTS report_period_start
            """
        )
    )
    db.commit()
