"""Daily completed/failed/duration/score rollups for evaluator results.

Charts read these rows. A finished run replaces its own day bucket, and a
dashboard load rebuilds the requested window only when the stored totals
disagree with the result table.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Set
from uuid import UUID

from sqlalchemy import String, and_, cast, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.database import CallRecording, CallRecordingSource, EvaluatorResult, EvaluatorResultDaily
from app.models.enums import EvaluatorResultStatus
from app.services.evaluators.evaluator_result_status import (
    _IN_FLIGHT_STATUSES,
    effective_evaluator_result_status,
    has_meaningful_metric_scores,
)

logger = logging.getLogger(__name__)

_TERMINAL = (
    EvaluatorResultStatus.COMPLETED.value,
    EvaluatorResultStatus.FAILED.value,
)


@dataclass
class DailySource:
    result_id: UUID
    agent_id: Optional[UUID]
    scenario_id: Optional[UUID]
    evaluator_id: Optional[UUID]
    timestamp: datetime
    status: str
    duration_seconds: Optional[float]
    metric_scores: Any
    is_live: bool


@dataclass
class DailyBucket:
    day: date
    agent_id: Optional[UUID]
    scenario_id: Optional[UUID]
    is_live: bool
    completed: int = 0
    failed: int = 0
    duration_seconds: float = 0
    duration_count: int = 0
    score: Dict[str, Dict[str, float]] = field(default_factory=dict)
    metric_ids: Set[str] = field(default_factory=set)


@dataclass
class RunDayTotal:
    day: date
    completed: int = 0
    failed: int = 0
    duration_seconds: float = 0
    duration_count: int = 0


@dataclass
class ScoreDayTotal:
    day: date
    metric_id: str
    score_sum: float = 0
    score_count: int = 0


@dataclass
class AgentMetricTotal:
    agent_id: UUID
    metric_count: int = 0


@dataclass
class DashboardSeries:
    run_days: List[RunDayTotal] = field(default_factory=list)
    score_days: List[ScoreDayTotal] = field(default_factory=list)
    agent_metric_counts: List[AgentMetricTotal] = field(default_factory=list)


def utc_day(value: datetime) -> date:
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(timezone.utc).date()


def _display_status(status: Optional[str], metric_scores: Any) -> str:
    return effective_evaluator_result_status(
        SimpleNamespace(status=status, metric_scores=metric_scores)
    )


def _numeric_score(entry: Any) -> Optional[float]:
    if not isinstance(entry, dict) or entry.get("skipped") or entry.get("error"):
        return None
    kind = str(entry.get("type") or "").lower()
    value = entry.get("value")
    if kind in ("number", "rating") and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if kind == "boolean":
        if value in (True, "true", 1, "1"):
            return 1.0
        if value in (False, "false", 0, "0"):
            return 0.0
    return None


def fold_daily_buckets(rows: Iterable[DailySource]) -> List[DailyBucket]:
    """Group finished runs into day, agent, scenario, and live/simulation buckets."""
    buckets: Dict[tuple, DailyBucket] = {}
    for row in rows:
        if row.timestamp is None:
            continue
        display = _display_status(row.status, row.metric_scores)
        if display not in _TERMINAL:
            continue
        day = utc_day(row.timestamp)
        key = (day, row.agent_id, row.scenario_id, row.is_live)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = DailyBucket(
                day=day,
                agent_id=row.agent_id,
                scenario_id=row.scenario_id,
                is_live=row.is_live,
            )
            buckets[key] = bucket
        if display == EvaluatorResultStatus.COMPLETED.value:
            bucket.completed += 1
        else:
            bucket.failed += 1
        if row.duration_seconds is not None:
            bucket.duration_seconds += float(row.duration_seconds)
            bucket.duration_count += 1
        scores = row.metric_scores if isinstance(row.metric_scores, dict) else {}
        if display == EvaluatorResultStatus.COMPLETED.value and has_meaningful_metric_scores(scores):
            for metric_id, entry in scores.items():
                metric_key = str(metric_id)
                bucket.metric_ids.add(metric_key)
                numeric = _numeric_score(entry)
                if numeric is None:
                    continue
                cell = bucket.score.setdefault(metric_key, {"sum": 0.0, "count": 0})
                cell["sum"] += numeric
                cell["count"] += 1
    return list(buckets.values())


def _live_result_ids(db: Session, result_ids: List[UUID]) -> Set[UUID]:
    if not result_ids:
        return set()
    rows = (
        db.query(CallRecording.evaluator_result_id)
        .filter(
            CallRecording.evaluator_result_id.in_(result_ids),
            CallRecording.source == CallRecordingSource.PLAYGROUND,
        )
        .all()
    )
    return {row[0] for row in rows if row[0]}


def _window_sources(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> List[DailySource]:
    query = db.query(
        EvaluatorResult.id,
        EvaluatorResult.agent_id,
        EvaluatorResult.scenario_id,
        EvaluatorResult.evaluator_id,
        EvaluatorResult.timestamp,
        EvaluatorResult.status,
        EvaluatorResult.duration_seconds,
        EvaluatorResult.metric_scores,
    ).filter(
        EvaluatorResult.organization_id == organization_id,
        EvaluatorResult.workspace_id == workspace_id,
    )
    if since is not None:
        query = query.filter(EvaluatorResult.timestamp >= _since_bound(since))
    if until is not None:
        query = query.filter(EvaluatorResult.timestamp <= _until_bound(until))
    loaded = query.all()
    live_ids = _live_result_ids(db, [row[0] for row in loaded])
    sources: List[DailySource] = []
    for result_id, agent_id, scenario_id, evaluator_id, timestamp, status, duration, scores in loaded:
        sources.append(
            DailySource(
                result_id=result_id,
                agent_id=agent_id,
                scenario_id=scenario_id,
                evaluator_id=evaluator_id,
                timestamp=timestamp,
                status=status,
                duration_seconds=duration,
                metric_scores=scores,
                is_live=evaluator_id is None or result_id in live_ids,
            )
        )
    return sources


def _write_buckets(db: Session, *, organization_id: UUID, workspace_id: UUID, buckets: List[DailyBucket]) -> None:
    now = datetime.now(timezone.utc)
    for bucket in buckets:
        if bucket.completed == 0 and bucket.failed == 0:
            continue
        db.add(
            EvaluatorResultDaily(
                organization_id=organization_id,
                workspace_id=workspace_id,
                usage_date=bucket.day,
                agent_id=bucket.agent_id,
                scenario_id=bucket.scenario_id,
                is_live=bucket.is_live,
                completed=bucket.completed,
                failed=bucket.failed,
                duration_seconds=bucket.duration_seconds,
                duration_count=bucket.duration_count,
                score={key: {"sum": cell["sum"], "count": cell["count"]} for key, cell in bucket.score.items()},
                metric_ids=sorted(bucket.metric_ids),
                updated_at=now,
            )
        )


def _since_bound(since: datetime) -> datetime:
    day = utc_day(since)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _until_bound(until: datetime) -> datetime:
    day = utc_day(until)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1) - timedelta(microseconds=1)


def _replace_window(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    since: Optional[datetime],
    until: Optional[datetime],
) -> None:
    query = db.query(EvaluatorResultDaily).filter(
        EvaluatorResultDaily.organization_id == organization_id,
        EvaluatorResultDaily.workspace_id == workspace_id,
    )
    if since is not None:
        query = query.filter(EvaluatorResultDaily.usage_date >= _since_bound(since).date())
    if until is not None:
        query = query.filter(EvaluatorResultDaily.usage_date <= _until_bound(until).date())
    query.delete(synchronize_session=False)
    _write_buckets(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        buckets=fold_daily_buckets(
            _window_sources(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                since=since,
                until=until,
            )
        ),
    )
    db.commit()


def _terminal_count(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    since: Optional[datetime],
    until: Optional[datetime],
) -> int:
    """Finished runs, including scored rows still marked in-flight."""
    scored_inflight = and_(
        EvaluatorResult.status.in_(list(_IN_FLIGHT_STATUSES)),
        EvaluatorResult.metric_scores.isnot(None),
        cast(EvaluatorResult.metric_scores, String).notin_(["{}", "null", ""]),
    )
    query = db.query(func.count(EvaluatorResult.id)).filter(
        EvaluatorResult.organization_id == organization_id,
        EvaluatorResult.workspace_id == workspace_id,
        or_(EvaluatorResult.status.in_(_TERMINAL), scored_inflight),
    )
    if since is not None:
        query = query.filter(EvaluatorResult.timestamp >= _since_bound(since))
    if until is not None:
        query = query.filter(EvaluatorResult.timestamp <= _until_bound(until))
    return int(query.scalar() or 0)


def _rollup_count(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    since: Optional[datetime],
    until: Optional[datetime],
) -> int:
    query = db.query(
        func.coalesce(
            func.sum(EvaluatorResultDaily.completed + EvaluatorResultDaily.failed),
            0,
        )
    ).filter(
        EvaluatorResultDaily.organization_id == organization_id,
        EvaluatorResultDaily.workspace_id == workspace_id,
    )
    if since is not None:
        query = query.filter(EvaluatorResultDaily.usage_date >= _since_bound(since).date())
    if until is not None:
        query = query.filter(EvaluatorResultDaily.usage_date <= _until_bound(until).date())
    return int(query.scalar() or 0)


def _series_from_rows(rows: Iterable[EvaluatorResultDaily]) -> DashboardSeries:
    by_day: Dict[date, RunDayTotal] = {}
    by_score: Dict[tuple, ScoreDayTotal] = {}
    metrics_by_agent: Dict[UUID, Set[str]] = defaultdict(set)
    for row in rows:
        day = by_day.get(row.usage_date)
        if day is None:
            day = RunDayTotal(day=row.usage_date)
            by_day[row.usage_date] = day
        day.completed += int(row.completed or 0)
        day.failed += int(row.failed or 0)
        day.duration_seconds += float(row.duration_seconds or 0)
        day.duration_count += int(row.duration_count or 0)
        score = row.score if isinstance(row.score, dict) else {}
        for metric_id, cell in score.items():
            if not isinstance(cell, dict):
                continue
            key = (row.usage_date, str(metric_id))
            point = by_score.get(key)
            if point is None:
                point = ScoreDayTotal(day=row.usage_date, metric_id=str(metric_id))
                by_score[key] = point
            point.score_sum += float(cell.get("sum") or 0)
            point.score_count += int(cell.get("count") or 0)
        if row.agent_id is not None:
            stored = row.metric_ids if isinstance(row.metric_ids, list) else []
            metrics_by_agent[row.agent_id].update(str(metric_id) for metric_id in stored)
    run_days = [by_day[day] for day in sorted(by_day)]
    score_days = sorted(by_score.values(), key=lambda item: (item.day, item.metric_id))
    agent_metrics = [
        AgentMetricTotal(agent_id=agent_id, metric_count=len(metric_ids))
        for agent_id, metric_ids in metrics_by_agent.items()
    ]
    agent_metrics.sort(key=lambda item: str(item.agent_id))
    return DashboardSeries(
        run_days=run_days,
        score_days=score_days,
        agent_metric_counts=agent_metrics,
    )


def _read_series(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: Optional[UUID],
    scenario_ids: Optional[Set[str]],
    since: Optional[datetime],
    until: Optional[datetime],
    playground: Optional[bool],
) -> DashboardSeries:
    query = db.query(EvaluatorResultDaily).filter(
        EvaluatorResultDaily.organization_id == organization_id,
        EvaluatorResultDaily.workspace_id == workspace_id,
        EvaluatorResultDaily.is_live == (playground is True),
    )
    if since is not None:
        query = query.filter(EvaluatorResultDaily.usage_date >= utc_day(since))
    if until is not None:
        query = query.filter(EvaluatorResultDaily.usage_date <= utc_day(until))
    if agent_id is not None:
        query = query.filter(EvaluatorResultDaily.agent_id == agent_id)
    if scenario_ids is not None:
        if not scenario_ids:
            return DashboardSeries()
        query = query.filter(EvaluatorResultDaily.scenario_id.in_([UUID(value) for value in scenario_ids]))
    return _series_from_rows(query.all())


def _series_from_buckets(
    buckets: Iterable[DailyBucket],
    *,
    agent_id: Optional[UUID],
    scenario_ids: Optional[Set[str]],
    playground: Optional[bool],
) -> DashboardSeries:
    live = playground is True
    by_day: Dict[date, RunDayTotal] = {}
    by_score: Dict[tuple, ScoreDayTotal] = {}
    metrics_by_agent: Dict[UUID, Set[str]] = defaultdict(set)
    for bucket in buckets:
        if bucket.is_live != live:
            continue
        if agent_id is not None and bucket.agent_id != agent_id:
            continue
        if scenario_ids is not None and (bucket.scenario_id is None or str(bucket.scenario_id) not in scenario_ids):
            continue
        day = by_day.get(bucket.day)
        if day is None:
            day = RunDayTotal(day=bucket.day)
            by_day[bucket.day] = day
        day.completed += bucket.completed
        day.failed += bucket.failed
        day.duration_seconds += bucket.duration_seconds
        day.duration_count += bucket.duration_count
        for metric_id, cell in bucket.score.items():
            key = (bucket.day, metric_id)
            point = by_score.get(key)
            if point is None:
                point = ScoreDayTotal(day=bucket.day, metric_id=metric_id)
                by_score[key] = point
            point.score_sum += float(cell.get("sum") or 0)
            point.score_count += int(cell.get("count") or 0)
        if bucket.agent_id is not None:
            metrics_by_agent[bucket.agent_id].update(bucket.metric_ids)
    return DashboardSeries(
        run_days=[by_day[day] for day in sorted(by_day)],
        score_days=sorted(by_score.values(), key=lambda item: (item.day, item.metric_id)),
        agent_metric_counts=sorted(
            (
                AgentMetricTotal(agent_id=owner, metric_count=len(metric_ids))
                for owner, metric_ids in metrics_by_agent.items()
            ),
            key=lambda item: str(item.agent_id),
        ),
    )


def load_dashboard_series(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: Optional[UUID],
    scenario_ids: Optional[Set[str]],
    since: Optional[datetime],
    until: Optional[datetime],
    playground: Optional[bool],
) -> DashboardSeries:
    """Read the daily table. Rebuild the window when its totals are stale."""
    try:
        if _terminal_count(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            since=since,
            until=until,
        ) != _rollup_count(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            since=since,
            until=until,
        ):
            _replace_window(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                since=since,
                until=until,
            )
        return _read_series(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            scenario_ids=scenario_ids,
            since=since,
            until=until,
            playground=playground,
        )
    except Exception:
        logger.warning("Evaluator result daily rollup unavailable; scanning the window", exc_info=True)
        db.rollback()
        try:
            return _series_from_buckets(
                fold_daily_buckets(
                    _window_sources(
                        db,
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        since=since,
                        until=until,
                    )
                ),
                agent_id=agent_id,
                scenario_ids=scenario_ids,
                playground=playground,
            )
        except Exception:
            logger.warning("Evaluator result daily scan failed", exc_info=True)
            db.rollback()
            return DashboardSeries()


def _bucket_filter(query, *, agent_id: Optional[UUID], scenario_id: Optional[UUID], is_live: bool):
    query = query.filter(EvaluatorResultDaily.is_live == is_live)
    if agent_id is None:
        query = query.filter(EvaluatorResultDaily.agent_id.is_(None))
    else:
        query = query.filter(EvaluatorResultDaily.agent_id == agent_id)
    if scenario_id is None:
        query = query.filter(EvaluatorResultDaily.scenario_id.is_(None))
    else:
        query = query.filter(EvaluatorResultDaily.scenario_id == scenario_id)
    return query


def record_evaluator_result_daily(db: Session, result: EvaluatorResult) -> None:
    """Replace the day bucket for a finished run. Safe to call again for the same run."""
    if result is None or result.timestamp is None or result.organization_id is None or result.workspace_id is None:
        return
    display = _display_status(result.status, result.metric_scores)
    if display not in _TERMINAL:
        return
    try:
        db.flush()
    except Exception:
        logger.warning("Could not flush evaluator result before daily rollup", exc_info=True)
    day = utc_day(result.timestamp)
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    loaded = (
        db.query(
            EvaluatorResult.id,
            EvaluatorResult.agent_id,
            EvaluatorResult.scenario_id,
            EvaluatorResult.evaluator_id,
            EvaluatorResult.timestamp,
            EvaluatorResult.status,
            EvaluatorResult.duration_seconds,
            EvaluatorResult.metric_scores,
        )
        .filter(
            EvaluatorResult.organization_id == result.organization_id,
            EvaluatorResult.workspace_id == result.workspace_id,
            EvaluatorResult.timestamp >= start,
            EvaluatorResult.timestamp < end,
            EvaluatorResult.agent_id.is_(None) if result.agent_id is None else EvaluatorResult.agent_id == result.agent_id,
            EvaluatorResult.scenario_id.is_(None) if result.scenario_id is None else EvaluatorResult.scenario_id == result.scenario_id,
        )
        .all()
    )
    live_ids = _live_result_ids(db, [row[0] for row in loaded])
    sources = [
        DailySource(
            result_id=result_id,
            agent_id=agent_id,
            scenario_id=scenario_id,
            evaluator_id=evaluator_id,
            timestamp=timestamp,
            status=status,
            duration_seconds=duration,
            metric_scores=scores,
            is_live=evaluator_id is None or result_id in live_ids,
        )
        for result_id, agent_id, scenario_id, evaluator_id, timestamp, status, duration, scores in loaded
    ]
    fresh = {
        (bucket.is_live): bucket
        for bucket in fold_daily_buckets(sources)
        if bucket.day == day and bucket.agent_id == result.agent_id and bucket.scenario_id == result.scenario_id
    }
    for is_live in (False, True):
        try:
            with db.begin_nested():
                existing = _bucket_filter(
                    db.query(EvaluatorResultDaily).filter(
                        EvaluatorResultDaily.organization_id == result.organization_id,
                        EvaluatorResultDaily.workspace_id == result.workspace_id,
                        EvaluatorResultDaily.usage_date == day,
                    ),
                    agent_id=result.agent_id,
                    scenario_id=result.scenario_id,
                    is_live=is_live,
                )
                bucket = fresh.get(is_live)
                row = existing.with_for_update(of=EvaluatorResultDaily).one_or_none()
                if bucket is None:
                    if row is not None:
                        db.delete(row)
                    continue
                if row is None:
                    row = EvaluatorResultDaily(
                        organization_id=result.organization_id,
                        workspace_id=result.workspace_id,
                        usage_date=day,
                        agent_id=result.agent_id,
                        scenario_id=result.scenario_id,
                        is_live=is_live,
                    )
                    db.add(row)
                row.completed = bucket.completed
                row.failed = bucket.failed
                row.duration_seconds = bucket.duration_seconds
                row.duration_count = bucket.duration_count
                row.score = {key: {"sum": cell["sum"], "count": cell["count"]} for key, cell in bucket.score.items()}
                row.metric_ids = sorted(bucket.metric_ids)
                row.updated_at = datetime.now(timezone.utc)
        except IntegrityError:
            logger.warning("Daily rollup bucket race for result %s; will reconcile on read", result.id)
