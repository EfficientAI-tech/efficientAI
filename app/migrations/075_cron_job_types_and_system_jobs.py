"""Migration: cron job types, system scheduled jobs, nullable org for platform tasks."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from croniter import croniter
import pytz
from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add cron job_type/is_system/config and seed platform system jobs"

_SYSTEM_JOB_IDS = {
    "usage_flush": uuid.UUID("00000000-0000-0000-0000-000000000001"),
    "alert_evaluate": uuid.UUID("00000000-0000-0000-0000-000000000002"),
    "oss_usage_prune": uuid.UUID("00000000-0000-0000-0000-000000000003"),
    "fx_rate_refresh": uuid.UUID("00000000-0000-0000-0000-000000000004"),
}


def _column_exists(db: Session, table: str, column: str) -> bool:
    return (
        db.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = :column_name
                """
            ),
            {"table_name": table, "column_name": column},
        ).first()
        is not None
    )


def _next_run(cron_expression: str, tz_name: str) -> datetime:
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    cron = croniter(cron_expression, now)
    return cron.get_next(datetime).astimezone(timezone.utc)


def upgrade(db: Session) -> None:
    if not _column_exists(db, "cron_jobs", "job_type"):
        db.execute(
            text(
                """
                ALTER TABLE cron_jobs
                ADD COLUMN job_type VARCHAR(64) NOT NULL DEFAULT 'evaluator_run'
                """
            )
        )
    if not _column_exists(db, "cron_jobs", "is_system"):
        db.execute(
            text(
                """
                ALTER TABLE cron_jobs
                ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT false
                """
            )
        )
    if not _column_exists(db, "cron_jobs", "config"):
        db.execute(
            text(
                """
                ALTER TABLE cron_jobs
                ADD COLUMN config JSONB NOT NULL DEFAULT '{}'::jsonb
                """
            )
        )

    db.execute(text("ALTER TABLE cron_jobs ALTER COLUMN organization_id DROP NOT NULL"))

    flush_cron = os.environ.get("USAGE_FLUSH_BEAT_SECONDS", "120")
    if flush_cron.isdigit():
        flush_expr = f"*/{max(1, int(flush_cron) // 60)} * * * *"
    else:
        flush_expr = "*/2 * * * *"

    system_jobs = [
        (
            _SYSTEM_JOB_IDS["usage_flush"],
            "__system_usage_flush",
            flush_expr,
            "usage_flush",
        ),
        (
            _SYSTEM_JOB_IDS["alert_evaluate"],
            "__system_alert_evaluate",
            "*/5 * * * *",
            "alert_evaluate",
        ),
        (
            _SYSTEM_JOB_IDS["oss_usage_prune"],
            "__system_oss_usage_prune",
            "0 3 * * *",
            "oss_usage_prune",
        ),
        (
            _SYSTEM_JOB_IDS["fx_rate_refresh"],
            "__system_fx_rate_refresh",
            "0 6 * * *",
            "fx_rate_refresh",
        ),
    ]

    for job_id, name, cron_expression, job_type in system_jobs:
        exists = db.execute(
            text("SELECT 1 FROM cron_jobs WHERE id = CAST(:id AS uuid)"),
            {"id": str(job_id)},
        ).first()
        if exists:
            continue
        next_run = _next_run(cron_expression, "UTC")
        db.execute(
            text(
                """
                INSERT INTO cron_jobs (
                    id, organization_id, name, cron_expression, timezone,
                    max_runs, current_runs, evaluator_ids, status,
                    next_run_at, job_type, is_system, config
                ) VALUES (
                    CAST(:id AS uuid), NULL, :name, :cron_expression, 'UTC',
                    2147483647, 0, CAST(:evaluator_ids AS jsonb), 'active',
                    :next_run_at, :job_type, true, CAST('{}' AS jsonb)
                )
                """
            ),
            {
                "id": str(job_id),
                "name": name,
                "cron_expression": cron_expression,
                "evaluator_ids": json.dumps([]),
                "next_run_at": next_run,
                "job_type": job_type,
            },
        )
        print(f"Seeded system cron job {job_type}")

    db.commit()


def downgrade(db: Session) -> None:
    for job_id in _SYSTEM_JOB_IDS.values():
        db.execute(
            text("DELETE FROM cron_jobs WHERE id = CAST(:id AS uuid)"),
            {"id": str(job_id)},
        )
    if _column_exists(db, "cron_jobs", "config"):
        db.execute(text("ALTER TABLE cron_jobs DROP COLUMN config"))
    if _column_exists(db, "cron_jobs", "is_system"):
        db.execute(text("ALTER TABLE cron_jobs DROP COLUMN is_system"))
    if _column_exists(db, "cron_jobs", "job_type"):
        db.execute(text("ALTER TABLE cron_jobs DROP COLUMN job_type"))
    db.commit()
