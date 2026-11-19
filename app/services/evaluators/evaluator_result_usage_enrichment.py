"""Merge provider recording + daily LLM usage onto evaluator result call_data for list views."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.database import CallRecording, CallRecordingSource, EvaluatorResult, LLMUsageDaily
from app.services.usage.context import LIVE_USAGE_SECTIONS, resolve_usage_role

_USAGE_OVERLAY_KEYS = (
    "cost",
    "costBreakdown",
    "cost_breakdown",
    "usage",
    "llm_token_usage",
    "call_cost",
    "metadata",
    "raw_data",
    "costs",
    "analysis",
    "model",
    "llm_model",
    "assistant",
    "durationSeconds",
    "duration_seconds",
    "duration_ms",
)


def merge_call_data_usage_fields(
    base: Optional[Dict[str, Any]],
    overlay: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Fill missing billing fields on evaluator call_data from a linked recording."""
    merged: Dict[str, Any] = dict(base) if isinstance(base, dict) else {}
    if not isinstance(overlay, dict):
        return merged
    for key in _USAGE_OVERLAY_KEYS:
        if key not in overlay:
            continue
        val = overlay[key]
        if val is None or val == "" or val == {}:
            continue
        existing = merged.get(key)
        if existing is None or existing == "" or existing == {}:
            merged[key] = val
    return merged


def _row_token_total(row: LLMUsageDaily) -> int:
    return int(
        (row.prompt_tokens or 0)
        + (row.completion_tokens or 0)
        + (row.cache_read_tokens or 0)
        + (row.cache_creation_tokens or 0)
        + (row.reasoning_tokens or 0)
    )


def apply_usage_rollup(
    call_data: Dict[str, Any],
    *,
    total_tokens: int,
    total_cost_micro_usd: int,
    by_model: Optional[Dict[str, Tuple[int, int]]] = None,
    by_role: Optional[Dict[str, Tuple[int, int]]] = None,
    usage_on: Optional[str] = None,
) -> Dict[str, Any]:
    """Inject rollup totals when provider call_data has no token/cost breakdown."""
    if total_tokens <= 0 and total_cost_micro_usd <= 0:
        return call_data
    usage = call_data.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    if total_tokens > 0 and not usage.get("total_tokens") and not usage.get("totalTokens"):
        usage["total_tokens"] = total_tokens
    cost_usd = total_cost_micro_usd / 1_000_000
    if cost_usd > 0 and not usage.get("total_cost_usd") and not usage.get("cost_usd"):
        usage["total_cost_usd"] = cost_usd
    call_data["usage"] = usage
    if by_model:
        usage_by_model: Dict[str, Dict[str, float | int]] = {}
        for model_name, (model_tokens, model_micro) in by_model.items():
            if model_tokens <= 0 and model_micro <= 0:
                continue
            usage_by_model[model_name] = {
                "total_tokens": model_tokens,
                "total_cost_usd": model_micro / 1_000_000,
            }
        if usage_by_model:
            call_data["usage_by_model"] = usage_by_model
    if by_role:
        usage_by_role: Dict[str, Dict[str, float | int]] = {}
        for role_key, (role_tokens, role_micro) in by_role.items():
            if role_tokens <= 0 and role_micro <= 0:
                continue
            usage_by_role[str(role_key)] = {
                "total_tokens": role_tokens,
                "total_cost_usd": role_micro / 1_000_000,
            }
        if usage_by_role:
            call_data["usage_by_role"] = usage_by_role
    if usage_on:
        call_data["usage_on"] = usage_on
    return call_data


def enrich_call_data_for_usage_display(
    call_data: Optional[Dict[str, Any]],
    *,
    recording_call_data: Optional[Dict[str, Any]] = None,
    rollup: Optional[Tuple[int, int]] = None,
    rollup_by_model: Optional[Dict[str, Tuple[int, int]]] = None,
    rollup_by_role: Optional[Dict[str, Tuple[int, int]]] = None,
    usage_on: Optional[str] = None,
) -> Dict[str, Any]:
    merged = merge_call_data_usage_fields(call_data, recording_call_data)
    if rollup:
        merged = apply_usage_rollup(
            merged,
            total_tokens=rollup[0],
            total_cost_micro_usd=rollup[1],
            by_model=rollup_by_model,
            by_role=rollup_by_role,
            usage_on=usage_on,
        )
    return merged


def batch_recordings_for_evaluator_results(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    result_ids: Sequence[UUID],
) -> Dict[UUID, CallRecording]:
    if not result_ids:
        return {}
    query = db.query(CallRecording).filter(
        CallRecording.evaluator_result_id.in_(list(result_ids)),
        CallRecording.organization_id == organization_id,
    )
    if workspace_id is not None:
        query = query.filter(CallRecording.workspace_id == workspace_id)
    recordings = query.order_by(CallRecording.created_at.desc()).all()
    from app.services.live_entity_storage import hydrate_call_recordings

    hydrate_call_recordings(recordings)
    out: Dict[UUID, CallRecording] = {}
    for row in recordings:
        if row.evaluator_result_id and row.evaluator_result_id not in out:
            out[row.evaluator_result_id] = row
    return out


def ensure_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Treat naive API datetimes as UTC so comparisons with aware bounds are safe."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_uuid(raw: Any) -> Optional[UUID]:
    if isinstance(raw, UUID):
        return raw
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _day_bounds(day: date) -> Tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(day, time.max, tzinfo=timezone.utc)
    return start, end


def _intersect_window(
    day: date,
    since: Optional[datetime],
    until: Optional[datetime],
) -> Tuple[datetime, datetime]:
    day_start, day_end = _day_bounds(day)
    since = ensure_utc_aware(since)
    until = ensure_utc_aware(until)
    start = day_start if since is None else max(day_start, since)
    end = day_end if until is None else min(day_end, until)
    return start, end


ShareKey = Tuple[UUID, Optional[UUID], str, date, Optional[UUID]]


def _share_key_from_row(row: LLMUsageDaily) -> Optional[ShareKey]:
    ctx = row.context if isinstance(row.context, dict) else {}
    agent_id = _parse_uuid(ctx.get("agent_id"))
    if agent_id is None:
        return None
    scenario_id = _parse_uuid(ctx.get("scenario_id"))
    model_name = (row.model or "").strip() or "Unknown model"
    usage_day = row.usage_date
    if usage_day is None:
        return None
    evaluator_id = _evaluator_id_from_context(ctx)
    return (agent_id, scenario_id, model_name, usage_day, evaluator_id)


def _result_share_key(result: EvaluatorResult, model_name: str) -> Optional[ShareKey]:
    if result.agent_id is None or result.timestamp is None:
        return None
    return (
        result.agent_id,
        result.scenario_id,
        model_name,
        result.timestamp.date(),
        result.evaluator_id,
    )


def _count_results_in_share_scope(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    agent_id: UUID,
    scenario_id: Optional[UUID],
    evaluator_id: Optional[UUID],
    usage_day: date,
    window_since: Optional[datetime],
    window_until: Optional[datetime],
) -> int:
    since_eff, until_eff = _intersect_window(usage_day, window_since, window_until)
    query = db.query(func.count(EvaluatorResult.id)).filter(
        EvaluatorResult.organization_id == organization_id,
        EvaluatorResult.agent_id == agent_id,
        EvaluatorResult.timestamp >= since_eff,
        EvaluatorResult.timestamp <= until_eff,
    )
    if workspace_id is not None:
        query = query.filter(EvaluatorResult.workspace_id == workspace_id)
    if scenario_id is not None:
        query = query.filter(EvaluatorResult.scenario_id == scenario_id)
    if evaluator_id is not None:
        query = query.filter(EvaluatorResult.evaluator_id == evaluator_id)
    return int(query.scalar() or 0)


def _evaluator_id_from_context(ctx: Dict[str, Any]) -> Optional[UUID]:
    resource_type = str(ctx.get("resource_type") or "").strip().lower()
    if resource_type == "evaluator":
        return _parse_uuid(ctx.get("resource_id"))
    return _parse_uuid(ctx.get("evaluator_id"))


def _result_matches_usage_row_scope(
    result: EvaluatorResult,
    *,
    row: LLMUsageDaily,
    since: Optional[datetime],
    until: Optional[datetime],
) -> bool:
    since = ensure_utc_aware(since)
    until = ensure_utc_aware(until)
    usage_day = row.usage_date
    if usage_day is None:
        return False
    if since is not None and usage_day < since.date():
        return False
    if until is not None and usage_day > until.date():
        return False
    if result.timestamp is None:
        return False
    day_start, day_end = _day_bounds(usage_day)
    if result.timestamp < day_start or result.timestamp > day_end:
        return False
    ctx = row.context if isinstance(row.context, dict) else {}
    agent_id = _parse_uuid(ctx.get("agent_id"))
    scenario_id = _parse_uuid(ctx.get("scenario_id"))
    evaluator_id = _evaluator_id_from_context(ctx)
    if agent_id is not None:
        if result.agent_id != agent_id:
            return False
        if evaluator_id is not None and result.evaluator_id != evaluator_id:
            return False
    else:
        if evaluator_id is None or result.evaluator_id != evaluator_id:
            return False
    if scenario_id is not None and result.scenario_id != scenario_id:
        return False
    return True


def _result_ids_for_usage_row(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    row: LLMUsageDaily,
    since: Optional[datetime],
    until: Optional[datetime],
    candidates: Optional[Sequence[EvaluatorResult]] = None,
) -> List[UUID]:
    since = ensure_utc_aware(since)
    until = ensure_utc_aware(until)
    ctx = row.context if isinstance(row.context, dict) else {}
    explicit = _parse_uuid(ctx.get("evaluator_result_id"))
    if explicit is not None:
        if candidates is not None:
            for item in candidates:
                if item.id == explicit:
                    if since is not None and item.timestamp and item.timestamp < since:
                        return []
                    if until is not None and item.timestamp and item.timestamp > until:
                        return []
                    return [explicit]
            return []
        scoped = db.query(EvaluatorResult.id).filter(
            EvaluatorResult.id == explicit,
            EvaluatorResult.organization_id == organization_id,
        )
        if workspace_id is not None:
            scoped = scoped.filter(EvaluatorResult.workspace_id == workspace_id)
        if since is not None:
            scoped = scoped.filter(EvaluatorResult.timestamp >= since)
        if until is not None:
            scoped = scoped.filter(EvaluatorResult.timestamp <= until)
        found = scoped.first()
        return [found.id] if found else []

    usage_day = row.usage_date
    if usage_day is None:
        return []
    day_start, day_end = _intersect_window(usage_day, since, until)

    if candidates is not None:
        return [
            item.id
            for item in candidates
            if item.organization_id == organization_id
            and (workspace_id is None or item.workspace_id == workspace_id)
            and _result_matches_usage_row_scope(item, row=row, since=since, until=until)
        ]

    agent_id = _parse_uuid(ctx.get("agent_id"))
    scenario_id = _parse_uuid(ctx.get("scenario_id"))
    evaluator_id = _evaluator_id_from_context(ctx)

    result_query = db.query(EvaluatorResult.id).filter(
        EvaluatorResult.organization_id == organization_id,
        EvaluatorResult.timestamp >= day_start,
        EvaluatorResult.timestamp <= day_end,
    )
    if workspace_id is not None:
        result_query = result_query.filter(EvaluatorResult.workspace_id == workspace_id)
    if agent_id is not None:
        result_query = result_query.filter(EvaluatorResult.agent_id == agent_id)
        if evaluator_id is not None:
            result_query = result_query.filter(EvaluatorResult.evaluator_id == evaluator_id)
    else:
        if evaluator_id is None:
            return []
        result_query = result_query.filter(EvaluatorResult.evaluator_id == evaluator_id)
    if scenario_id is not None:
        result_query = result_query.filter(EvaluatorResult.scenario_id == scenario_id)
    return [result_id for (result_id,) in result_query.all()]


def _query_usage_rows_for_page(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    usage_since: date,
    usage_until: date,
    page_ids: Set[UUID],
    page_agent_ids: Set[UUID],
    page_evaluator_ids: Set[UUID],
    page_days: Set[date],
) -> List[LLMUsageDaily]:
    """Load only ledger rows that can attribute to this result page."""
    scope_filters = []
    if page_ids:
        scope_filters.append(
            LLMUsageDaily.context["evaluator_result_id"].astext.in_([str(rid) for rid in page_ids])
        )
    day_list = list(page_days) if page_days else []
    if page_agent_ids and day_list:
        for aid in page_agent_ids:
            scope_filters.append(
                and_(
                    LLMUsageDaily.context["agent_id"].astext == str(aid),
                    LLMUsageDaily.usage_date.in_(day_list),
                )
            )
    if page_evaluator_ids and day_list:
        for eid in page_evaluator_ids:
            scope_filters.append(
                and_(
                    or_(
                        and_(
                            LLMUsageDaily.context["resource_type"].astext == "evaluator",
                            LLMUsageDaily.context["resource_id"].astext == str(eid),
                        ),
                        LLMUsageDaily.context["evaluator_id"].astext == str(eid),
                    ),
                    LLMUsageDaily.usage_date.in_(day_list),
                )
            )
    if not scope_filters:
        return []

    query = db.query(LLMUsageDaily).filter(
        LLMUsageDaily.organization_id == organization_id,
        LLMUsageDaily.usage_date >= usage_since,
        LLMUsageDaily.usage_date <= usage_until,
        or_(*scope_filters),
    )
    if workspace_id is not None:
        query = query.filter(LLMUsageDaily.workspace_id == workspace_id)
    return query.all()


def _role_key_from_usage_row(row: LLMUsageDaily) -> Optional[str]:
    ctx = row.context if isinstance(row.context, dict) else {}
    return resolve_usage_role(row.product_section or "", ctx)


def _add_role_slice(
    by_role: Dict[str, Dict[str, Tuple[int, int]]],
    result_key: str,
    role: Optional[str],
    tokens: int,
    micro: int,
) -> None:
    if not role or (tokens <= 0 and micro <= 0):
        return
    bucket = by_role[result_key]
    prev_tokens, prev_micro = bucket.get(role, (0, 0))
    bucket[role] = (prev_tokens + tokens, prev_micro + micro)


def batch_llm_usage_rollups_for_results(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    results: Sequence[EvaluatorResult],
    usage_since: Optional[date] = None,
    usage_until: Optional[date] = None,
    window_since: Optional[datetime] = None,
    window_until: Optional[datetime] = None,
) -> Tuple[
    Dict[str, Tuple[int, int]],
    Dict[str, Dict[str, Tuple[int, int]]],
    Dict[str, Dict[str, Tuple[int, int]]],
    Dict[str, str],
]:
    rows = list(results)
    if not rows:
        return {}, {}, {}, {}
    result_days = {row.timestamp.date() for row in rows if row.timestamp is not None}
    if usage_since is None and result_days:
        usage_since = min(result_days)
    if usage_until is None and result_days:
        usage_until = max(result_days)
    if usage_since is None or usage_until is None:
        return {}, {}, {}, {}

    page_ids = {row.id for row in rows}
    page_agent_ids = {row.agent_id for row in rows if row.agent_id is not None}
    page_evaluator_ids = {row.evaluator_id for row in rows if row.evaluator_id is not None}
    page_days = result_days or {usage_since, usage_until}
    page_share_keys: Set[ShareKey] = set()

    raw_usage_rows = _query_usage_rows_for_page(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        usage_since=usage_since,
        usage_until=usage_until,
        page_ids=page_ids,
        page_agent_ids=page_agent_ids,
        page_evaluator_ids=page_evaluator_ids,
        page_days=page_days,
    )
    usage_rows: List[LLMUsageDaily] = []
    seen_row_ids: Set[Any] = set()
    for row in raw_usage_rows:
        if row.id in seen_row_ids:
            continue
        seen_row_ids.add(row.id)
        ctx = row.context if isinstance(row.context, dict) else {}
        explicit = _parse_uuid(ctx.get("evaluator_result_id"))
        if explicit is not None:
            if explicit in page_ids:
                usage_rows.append(row)
            continue
        share = _share_key_from_row(row)
        if share is not None:
            agent_id, scenario_id, _model, usage_day, share_evaluator_id = share
            if usage_day in page_days and agent_id in page_agent_ids:
                needs_row_match = scenario_id is not None or share_evaluator_id is not None
                row_match = any(
                    r.agent_id == agent_id
                    and (share_evaluator_id is None or r.evaluator_id == share_evaluator_id)
                    and (scenario_id is None or r.scenario_id == scenario_id)
                    and r.timestamp is not None
                    and r.timestamp.date() == usage_day
                    for r in rows
                )
                if not needs_row_match or row_match:
                    usage_rows.append(row)
                    page_share_keys.add(share)
            continue
        evaluator_id = _evaluator_id_from_context(ctx)
        if evaluator_id in page_evaluator_ids and row.usage_date in page_days:
            usage_rows.append(row)
            continue
        agent_id = _parse_uuid(ctx.get("agent_id"))
        if agent_id in page_agent_ids and row.usage_date in page_days:
            usage_rows.append(row)

    totals: Dict[str, Tuple[int, int]] = defaultdict(lambda: (0, 0))
    by_model: Dict[str, Dict[str, Tuple[int, int]]] = defaultdict(dict)
    by_role: Dict[str, Dict[str, Tuple[int, int]]] = defaultdict(dict)
    usage_days: Dict[str, Set[str]] = defaultdict(set)
    share_buckets: Dict[ShareKey, Tuple[int, int]] = defaultdict(lambda: (0, 0))
    share_roles: Dict[ShareKey, Dict[str, Tuple[int, int]]] = defaultdict(dict)
    share_run_count: Dict[ShareKey, int] = {}

    window_since = ensure_utc_aware(window_since)
    window_until = ensure_utc_aware(window_until)
    if window_since is None and usage_since is not None:
        window_since = datetime.combine(usage_since, time.min, tzinfo=timezone.utc)
    if window_until is None and usage_until is not None:
        window_until = datetime.combine(usage_until, time.max, tzinfo=timezone.utc)

    for row in usage_rows:
        tokens = _row_token_total(row)
        micro = int(row.total_cost_micro_usd or 0)
        if tokens <= 0 and micro <= 0:
            continue
        ctx = row.context if isinstance(row.context, dict) else {}
        model_name = (row.model or "Unknown model").strip() or "Unknown model"
        usage_role = _role_key_from_usage_row(row)
        result_id = str(ctx.get("evaluator_result_id") or "").strip()
        if result_id:
            prev_tokens, prev_micro = totals[result_id]
            totals[result_id] = (prev_tokens + tokens, prev_micro + micro)
            model_bucket = by_model[result_id]
            prev_m_tokens, prev_m_micro = model_bucket.get(model_name, (0, 0))
            model_bucket[model_name] = (prev_m_tokens + tokens, prev_m_micro + micro)
            _add_role_slice(by_role, result_id, usage_role, tokens, micro)
            if row.usage_date is not None:
                usage_days[result_id].add(row.usage_date.isoformat())
            continue
        share = _share_key_from_row(row)
        if share is None:
            continue
        prev_tokens, prev_micro = share_buckets[share]
        share_buckets[share] = (prev_tokens + tokens, prev_micro + micro)
        page_share_keys.add(share)
        if usage_role:
            role_bucket = share_roles[share]
            pt, pm = role_bucket.get(usage_role, (0, 0))
            role_bucket[usage_role] = (pt + tokens, pm + micro)

    for share_key in share_buckets:
        if share_key in share_run_count:
            continue
        agent_id, scenario_id, _model, usage_day, evaluator_id = share_key
        share_run_count[share_key] = _count_results_in_share_scope(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            scenario_id=scenario_id,
            evaluator_id=evaluator_id,
            usage_day=usage_day,
            window_since=window_since,
            window_until=window_until,
        )

    page_id_str = {str(rid) for rid in page_ids}

    for result in rows:
        result_key = str(result.id)
        for share, (bucket_tokens, bucket_micro) in share_buckets.items():
            if _result_share_key(result, share[2]) != share:
                continue
            model_name = share[2]
            run_count = max(1, share_run_count.get(share, 1))
            share_tokens = bucket_tokens // run_count
            share_micro = bucket_micro // run_count
            if share_tokens <= 0 and share_micro <= 0:
                continue
            prev_tokens, prev_micro = totals[result_key]
            totals[result_key] = (prev_tokens + share_tokens, prev_micro + share_micro)
            model_bucket = by_model[result_key]
            prev_m_tokens, prev_m_micro = model_bucket.get(model_name, (0, 0))
            model_bucket[model_name] = (prev_m_tokens + share_tokens, prev_m_micro + share_micro)
            for role, (role_tokens, role_micro) in share_roles.get(share, {}).items():
                r_tok = role_tokens // run_count
                r_mic = role_micro // run_count
                _add_role_slice(by_role, result_key, role, r_tok, r_mic)
            usage_days[result_key].add(share[3].isoformat())

    fallback_rows = [
        row
        for row in usage_rows
        if _share_key_from_row(row) is None and not _parse_uuid((row.context or {}).get("evaluator_result_id"))
    ]
    if fallback_rows:
        for row in fallback_rows:
            tokens = _row_token_total(row)
            micro = int(row.total_cost_micro_usd or 0)
            if tokens <= 0 and micro <= 0:
                continue
            model_name = (row.model or "").strip() or "Unknown model"
            usage_role = _role_key_from_usage_row(row)
            ids = _result_ids_for_usage_row(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                row=row,
                since=window_since,
                until=window_until,
                candidates=rows,
            )
            ids = [rid for rid in ids if str(rid) in page_id_str]
            if not ids:
                continue
            share_tokens = tokens // len(ids)
            share_micro = micro // len(ids)
            for result_id in ids:
                result_key = str(result_id)
                prev_tokens, prev_micro = totals[result_key]
                totals[result_key] = (prev_tokens + share_tokens, prev_micro + share_micro)
                model_bucket = by_model[result_key]
                prev_m_tokens, prev_m_micro = model_bucket.get(model_name, (0, 0))
                model_bucket[model_name] = (prev_m_tokens + share_tokens, prev_m_micro + share_micro)
                _add_role_slice(by_role, result_key, usage_role, share_tokens, share_micro)
                if row.usage_date is not None:
                    usage_days[result_key].add(row.usage_date.isoformat())

    return (
        dict(totals),
        {key: dict(value) for key, value in by_model.items()},
        {key: dict(value) for key, value in by_role.items()},
        {key: min(days) for key, days in usage_days.items() if days},
    )


def _usage_row_matches_playground_mode(row: LLMUsageDaily, playground: Optional[bool]) -> bool:
    if playground is None:
        return True
    section = row.product_section or ""
    live = section in LIVE_USAGE_SECTIONS
    return playground == live


def _fetch_implicit_usage_candidates(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    rows: Sequence[LLMUsageDaily],
    since: Optional[datetime],
    until: Optional[datetime],
) -> List[EvaluatorResult]:
    agent_ids: Set[UUID] = set()
    evaluator_ids: Set[UUID] = set()
    usage_days: Set[date] = set()
    for row in rows:
        ctx = row.context if isinstance(row.context, dict) else {}
        if _parse_uuid(ctx.get("evaluator_result_id")):
            continue
        usage_day = row.usage_date
        if usage_day is None:
            continue
        usage_days.add(usage_day)
        agent_id = _parse_uuid(ctx.get("agent_id"))
        if agent_id is not None:
            agent_ids.add(agent_id)
        else:
            evaluator_id = _evaluator_id_from_context(ctx)
            if evaluator_id is not None:
                evaluator_ids.add(evaluator_id)
    if not usage_days:
        return []
    day_min = min(usage_days)
    day_max = max(usage_days)
    range_start, _ = _day_bounds(day_min)
    _, range_end = _day_bounds(day_max)
    since = ensure_utc_aware(since)
    until = ensure_utc_aware(until)
    if since is not None:
        range_start = max(range_start, since)
    if until is not None:
        range_end = min(range_end, until)

    filters = []
    if agent_ids:
        filters.append(EvaluatorResult.agent_id.in_(agent_ids))
    if evaluator_ids:
        filters.append(EvaluatorResult.evaluator_id.in_(evaluator_ids))
    if not filters:
        return []

    query = db.query(EvaluatorResult).filter(
        EvaluatorResult.organization_id == organization_id,
        EvaluatorResult.timestamp >= range_start,
        EvaluatorResult.timestamp <= range_end,
        or_(*filters),
    )
    if workspace_id is not None:
        query = query.filter(EvaluatorResult.workspace_id == workspace_id)
    return query.all()


def _playground_result_ids(
    db: Session,
    organization_id: UUID,
    workspace_id: Optional[UUID],
) -> Set[UUID]:
    recording_query = db.query(CallRecording.evaluator_result_id).filter(
        CallRecording.organization_id == organization_id,
        CallRecording.source == CallRecordingSource.PLAYGROUND,
        CallRecording.evaluator_result_id.isnot(None),
    )
    result_query = db.query(EvaluatorResult.id).filter(
        EvaluatorResult.organization_id == organization_id,
        EvaluatorResult.evaluator_id.is_(None),
    )
    if workspace_id is not None:
        recording_query = recording_query.filter(CallRecording.workspace_id == workspace_id)
        result_query = result_query.filter(EvaluatorResult.workspace_id == workspace_id)
    ids = {rid for (rid,) in recording_query.all() if rid is not None}
    ids.update(rid for (rid,) in result_query.all())
    return ids


def _scoped_evaluator_result_query(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    agent_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
    suite_id: Optional[UUID] = None,
    evaluator_id: Optional[UUID] = None,
):
    from app.models.database import Evaluator

    query = db.query(EvaluatorResult.id).filter(
        EvaluatorResult.organization_id == organization_id,
    )
    if workspace_id is not None:
        query = query.filter(EvaluatorResult.workspace_id == workspace_id)
    if agent_id is not None:
        query = query.filter(EvaluatorResult.agent_id == agent_id)
    if scenario_id is not None:
        query = query.filter(EvaluatorResult.scenario_id == scenario_id)
    if evaluator_id is not None:
        query = query.filter(EvaluatorResult.evaluator_id == evaluator_id)
    if suite_id is not None:
        query = query.join(Evaluator, EvaluatorResult.evaluator_id == Evaluator.id).filter(
            Evaluator.suite_id == suite_id
        )
    return query


def evaluator_result_ids_with_usage_model(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    model: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    playground: Optional[bool] = None,
    agent_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
    suite_id: Optional[UUID] = None,
    evaluator_id: Optional[UUID] = None,
) -> Tuple[List[UUID], int]:
    model_key = (model or "").strip()
    if not model_key:
        return [], 0
    usage_query = db.query(LLMUsageDaily).filter(
        LLMUsageDaily.organization_id == organization_id,
        func.lower(LLMUsageDaily.model) == model_key.lower(),
    )
    if workspace_id is not None:
        usage_query = usage_query.filter(LLMUsageDaily.workspace_id == workspace_id)
    if since is not None:
        usage_query = usage_query.filter(LLMUsageDaily.usage_date >= since.date())
    if until is not None:
        usage_query = usage_query.filter(LLMUsageDaily.usage_date <= until.date())

    playground_ids = _playground_result_ids(db, organization_id, workspace_id) if playground is not None else None
    usage_rows: List[LLMUsageDaily] = []
    for row in usage_query.all():
        ctx = row.context if isinstance(row.context, dict) else {}
        explicit = _parse_uuid(ctx.get("evaluator_result_id"))
        if explicit is not None and playground_ids is not None:
            if (explicit in playground_ids) != bool(playground):
                continue
        elif not _usage_row_matches_playground_mode(row, playground):
            continue
        usage_rows.append(row)
    if not usage_rows:
        return [], 0

    out: Set[UUID] = set()
    attributed_micro = 0
    implicit_rows: List[LLMUsageDaily] = []
    explicit_ids: List[UUID] = []
    for row in usage_rows:
        ctx = row.context if isinstance(row.context, dict) else {}
        explicit = _parse_uuid(ctx.get("evaluator_result_id"))
        if explicit is not None:
            explicit_ids.append(explicit)
        else:
            implicit_rows.append(row)

    scoped = _scoped_evaluator_result_query(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        scenario_id=scenario_id,
        suite_id=suite_id,
        evaluator_id=evaluator_id,
    )

    if explicit_ids:
        verified = scoped.filter(EvaluatorResult.id.in_(explicit_ids))
        matched = {rid for (rid,) in verified.all()}
        out.update(matched)
        for row in usage_rows:
            ctx = row.context if isinstance(row.context, dict) else {}
            explicit = _parse_uuid(ctx.get("evaluator_result_id"))
            if explicit in matched:
                attributed_micro += int(row.total_cost_micro_usd or 0)

    candidates = _fetch_implicit_usage_candidates(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        rows=implicit_rows,
        since=since,
        until=until,
    )
    for row in implicit_rows:
        matched_ids = _result_ids_for_usage_row(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            row=row,
            since=since,
            until=until,
            candidates=candidates,
        )
        if not matched_ids:
            continue
        scoped_matched = {
            rid for (rid,) in scoped.filter(EvaluatorResult.id.in_(matched_ids)).all()
        }
        if not scoped_matched:
            continue
        out.update(scoped_matched)
        if len(scoped_matched) == len(matched_ids):
            attributed_micro += int(row.total_cost_micro_usd or 0)
        else:
            attributed_micro += int(
                (int(row.total_cost_micro_usd or 0) * len(scoped_matched)) / len(matched_ids)
            )
    return list(out), attributed_micro


def usage_enrichment_caches_for_results(
    db: Session,
    results: Iterable[EvaluatorResult],
    *,
    usage_since: Optional[date] = None,
    usage_until: Optional[date] = None,
    window_since: Optional[datetime] = None,
    window_until: Optional[datetime] = None,
) -> Tuple[
    Dict[UUID, CallRecording],
    Dict[str, Tuple[int, int]],
    Dict[str, Dict[str, Tuple[int, int]]],
    Dict[str, Dict[str, Tuple[int, int]]],
    Dict[str, str],
]:
    rows = list(results)
    if not rows:
        return {}, {}, {}, {}, {}
    window_since = ensure_utc_aware(window_since)
    window_until = ensure_utc_aware(window_until)
    organization_id = rows[0].organization_id
    workspace_id = rows[0].workspace_id
    result_ids = [row.id for row in rows]
    recordings = batch_recordings_for_evaluator_results(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        result_ids=result_ids,
    )
    rollups, rollups_by_model, rollups_by_role, usage_days = batch_llm_usage_rollups_for_results(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        results=rows,
        usage_since=usage_since,
        usage_until=usage_until,
        window_since=window_since,
        window_until=window_until,
    )
    return recordings, rollups, rollups_by_model, rollups_by_role, usage_days