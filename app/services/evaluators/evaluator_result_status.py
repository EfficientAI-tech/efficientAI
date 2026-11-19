"""Helpers for evaluator result lifecycle and status consistency."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.database import EvaluatorResult
from app.models.enums import EvaluatorResultStatus

_IN_FLIGHT_STATUSES = frozenset(
    {
        EvaluatorResultStatus.QUEUED.value,
        EvaluatorResultStatus.TRANSCRIBING.value,
        EvaluatorResultStatus.EVALUATING.value,
        EvaluatorResultStatus.FETCHING_DETAILS.value,
    }
)


def has_meaningful_metric_scores(metric_scores: Any) -> bool:
    if not metric_scores or not isinstance(metric_scores, dict):
        return False
    return len(metric_scores) > 0


def repair_evaluator_result_failed_status_if_needed(
    db: Session,
    result: EvaluatorResult,
    *,
    commit: bool = True,
) -> bool:
    """Align stored status with effective status when scores are fatal error-only."""
    if result.status != EvaluatorResultStatus.COMPLETED.value:
        return False
    if not _metric_scores_mark_failed(result.metric_scores):
        return False
    result.status = EvaluatorResultStatus.FAILED.value
    result.error_message = result.error_message or "Evaluation metrics could not be scored"
    if commit:
        db.commit()
        db.refresh(result)
    return True


def repair_evaluator_result_status_if_needed(
    db: Session,
    result: EvaluatorResult,
    *,
    commit: bool = True,
) -> bool:
    """Fix rows that have scores but were left in an in-flight status (stale worker/UI state)."""
    if not has_meaningful_metric_scores(result.metric_scores):
        return False
    if result.status not in _IN_FLIGHT_STATUSES:
        return False

    result.status = EvaluatorResultStatus.COMPLETED.value
    if result.error_message:
        result.error_message = None
    if commit:
        db.commit()
        db.refresh(result)
    return True


# Metric-level fallbacks (audio_failed, llm_failed) still complete the run; only fatal
# scoring outcomes should surface as failed in filters and persisted status.
EVALUATION_FATAL_SCORE_ERRORS = frozenset({"llm_parse_failed"})


def _metric_scores_mark_failed(metric_scores: Any) -> bool:
    if not isinstance(metric_scores, dict) or not metric_scores:
        return False
    has_scored_value = False
    has_fatal_error = False
    for entry in metric_scores.values():
        if not isinstance(entry, dict):
            continue
        error = entry.get("error")
        if error in EVALUATION_FATAL_SCORE_ERRORS:
            has_fatal_error = True
        if entry.get("skipped"):
            continue
        if entry.get("value") is not None:
            has_scored_value = True
    return has_fatal_error and not has_scored_value


def effective_evaluator_result_status(result: EvaluatorResult) -> str:
    """Status string safe for API responses when DB row is slightly stale."""
    if _metric_scores_mark_failed(result.metric_scores):
        return EvaluatorResultStatus.FAILED.value
    if has_meaningful_metric_scores(result.metric_scores) and result.status in _IN_FLIGHT_STATUSES:
        return EvaluatorResultStatus.COMPLETED.value
    return result.status or EvaluatorResultStatus.QUEUED.value
