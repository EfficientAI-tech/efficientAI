"""Compute and persist evaluation report period (ISO week) without full row scans."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.db_sharding.scatter_gather import query_completed_recording_date_bounds
from app.models.database import CallImportEvaluation


def report_period_from_recording_bounds(
    min_date: date,
    max_date: date,
) -> Tuple[date, date, str, str]:
    """Match ``_report_period_from_rows`` week labeling (anchor = latest date)."""
    start = min_date
    end = max_date
    week_anchor = max_date
    week_start = week_anchor - timedelta(days=week_anchor.weekday())
    week_end = week_start + timedelta(days=6)
    iso_year, iso_week, _ = week_anchor.isocalendar()
    label = f"{iso_year}-W{iso_week:02d}"
    if week_start.year == week_end.year:
        week_range = f"{week_start.strftime('%b %d')}–{week_end.strftime('%b %d, %Y')}"
    else:
        week_range = (
            f"{week_start.strftime('%b %d, %Y')}–{week_end.strftime('%b %d, %Y')}"
        )
    display = f"W{iso_week:02d} · {week_range}"
    return start, end, label, display


def evaluation_report_period_is_current(evaluation: CallImportEvaluation) -> bool:
    completed = int(evaluation.completed_rows or 0)
    cached_at = evaluation.report_period_at_count
    if cached_at is None:
        return False
    if int(cached_at) != completed:
        return False
    return evaluation.report_period_start is not None or completed == 0


def refresh_evaluation_report_period(
    db: Session,
    evaluation: CallImportEvaluation,
) -> None:
    """Recompute period from SQL min/max recording dates for completed rows."""
    completed = int(evaluation.completed_rows or 0)
    min_date, max_date = query_completed_recording_date_bounds(db, evaluation.id)
    if min_date is None or max_date is None:
        evaluation.report_period_start = None
        evaluation.report_period_end = None
        evaluation.report_period_label = None
        evaluation.report_period_display = None
    else:
        start, end, label, display = report_period_from_recording_bounds(
            min_date, max_date
        )
        evaluation.report_period_start = start
        evaluation.report_period_end = end
        evaluation.report_period_label = label
        evaluation.report_period_display = display
    evaluation.report_period_at_count = completed


def ensure_evaluation_report_period(
    db: Session,
    evaluation: CallImportEvaluation,
    *,
    force: bool = False,
) -> None:
    if not force and evaluation_report_period_is_current(evaluation):
        return
    refresh_evaluation_report_period(db, evaluation)


def report_period_tuple(
    evaluation: CallImportEvaluation,
) -> tuple[Optional[date], Optional[date], Optional[str], str]:
    if evaluation.report_period_start is None:
        return None, None, None, evaluation.report_period_display or "Not specified"
    return (
        evaluation.report_period_start,
        evaluation.report_period_end,
        evaluation.report_period_label,
        evaluation.report_period_display or "Not specified",
    )
