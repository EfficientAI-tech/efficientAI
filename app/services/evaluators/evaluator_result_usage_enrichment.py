"""Merge provider recording + daily LLM usage onto evaluator result call_data for list views."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database import CallRecording, EvaluatorResult, LLMUsageDaily
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
    return call_data


def enrich_call_data_for_usage_display(
    call_data: Optional[Dict[str, Any]],
    *,
    recording_call_data: Optional[Dict[str, Any]] = None,
    rollup: Optional[Tuple[int, int]] = None,
    rollup_by_model: Optional[Dict[str, Tuple[int, int]]] = None,
    rollup_by_role: Optional[Dict[str, Tuple[int, int]]] = None,
) -> Dict[str, Any]:
    merged = merge_call_data_usage_fields(call_data, recording_call_data)
    if rollup:
        merged = apply_usage_rollup(
            merged,
            total_tokens=rollup[0],
            total_cost_micro_usd=rollup[1],
            by_model=rollup_by_model,
            by_role=rollup_by_role,
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


ShareKey = Tuple[UUID, Optional[UUID], str]


def _share_key_from_row(row: LLMUsageDaily) -> Optional[ShareKey]:
    ctx = row.context if isinstance(row.context, dict) else {}
    agent_id = _parse_uuid(ctx.get("agent_id"))
    if agent_id is None:
        return None
    scenario_id = _parse_uuid(ctx.get("scenario_id"))
    model_name = (row.model or "").strip() or "Unknown model"
    return (agent_id, scenario_id, model_name)


def _result_share_key(result: EvaluatorResult, model_name: str) -> Optional[ShareKey]:
    if result.agent_id is None:
        return None
    return (result.agent_id, result.scenario_id, model_name)


def _count_results_in_share_scope(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    agent_id: UUID,
    scenario_id: Optional[UUID],
    since: Optional[datetime],
    until: Optional[datetime],
) -> int:
    query = db.query(func.count(EvaluatorResult.id)).filter(
        EvaluatorResult.organization_id == organization_id,
        EvaluatorResult.agent_id == agent_id,
    )
    if workspace_id is not None:
        query = query.filter(EvaluatorResult.workspace_id == workspace_id)
    if scenario_id is not None:
        query = query.filter(EvaluatorResult.scenario_id == scenario_id)
    if since is not None:
        query = query.filter(EvaluatorResult.timestamp >= since)
    if until is not None:
        query = query.filter(EvaluatorResult.timestamp <= until)
    return int(query.scalar() or 0)


def _evaluator_id_from_context(ctx: Dict[str, Any]) -> Optional[UUID]:
    resource_type = str(ctx.get("resource_type") or "").strip().lower()
    if resource_type == "evaluator":
        return _parse_uuid(ctx.get("resource_id"))
    return _parse_uuid(ctx.get("evaluator_id"))


def _result_ids_for_usage_row(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    row: LLMUsageDaily,
    since: Optional[datetime],
    until: Optional[datetime],
) -> List[UUID]:
    ctx = row.context if isinstance(row.context, dict) else {}
    explicit = _parse_uuid(ctx.get("evaluator_result_id"))
    if explicit is not None:
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
        row = scoped.first()
        return [row.id] if row else []

    if since is not None and row.usage_date < since.date():
        return []
    if until is not None and row.usage_date > until.date():
        return []

    agent_id = _parse_uuid(ctx.get("agent_id"))
    scenario_id = _parse_uuid(ctx.get("scenario_id"))

    result_query = db.query(EvaluatorResult.id).filter(
        EvaluatorResult.organization_id == organization_id,
    )
    if since is not None:
        result_query = result_query.filter(EvaluatorResult.timestamp >= since)
    if until is not None:
        result_query = result_query.filter(EvaluatorResult.timestamp <= until)
    if workspace_id is not None:
        result_query = result_query.filter(EvaluatorResult.workspace_id == workspace_id)
    if agent_id is not None:
        result_query = result_query.filter(EvaluatorResult.agent_id == agent_id)
    else:
        evaluator_id = _evaluator_id_from_context(ctx)
        if evaluator_id is None:
            return []
        result_query = result_query.filter(EvaluatorResult.evaluator_id == evaluator_id)
    if scenario_id is not None:
        result_query = result_query.filter(EvaluatorResult.scenario_id == scenario_id)
    return [result_id for (result_id,) in result_query.all()]


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
) -> Tuple[
    Dict[str, Tuple[int, int]],
    Dict[str, Dict[str, Tuple[int, int]]],
    Dict[str, Dict[str, Tuple[int, int]]],
]:
    rows = list(results)
    if not rows:
        return {}, {}, {}
    result_days = {row.timestamp.date() for row in rows if row.timestamp is not None}
    if usage_since is None and result_days:
        usage_since = min(result_days)
    if usage_until is None and result_days:
        usage_until = max(result_days)
    if usage_since is None or usage_until is None:
        return {}, {}, {}
    usage_query = db.query(LLMUsageDaily).filter(
        LLMUsageDaily.organization_id == organization_id,
        LLMUsageDaily.usage_date >= usage_since,
        LLMUsageDaily.usage_date <= usage_until,
    )
    if workspace_id is not None:
        usage_query = usage_query.filter(LLMUsageDaily.workspace_id == workspace_id)

    totals: Dict[str, Tuple[int, int]] = defaultdict(lambda: (0, 0))
    by_model: Dict[str, Dict[str, Tuple[int, int]]] = defaultdict(dict)
    by_role: Dict[str, Dict[str, Tuple[int, int]]] = defaultdict(dict)
    share_buckets: Dict[ShareKey, Tuple[int, int]] = defaultdict(lambda: (0, 0))
    share_roles: Dict[ShareKey, Dict[str, Tuple[int, int]]] = defaultdict(dict)
    share_run_count: Dict[ShareKey, int] = {}

    for row in usage_query.all():
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
            continue
        share = _share_key_from_row(row)
        if share is None:
            continue
        prev_tokens, prev_micro = share_buckets[share]
        share_buckets[share] = (prev_tokens + tokens, prev_micro + micro)
        if usage_role:
            role_bucket = share_roles[share]
            pt, pm = role_bucket.get(usage_role, (0, 0))
            role_bucket[usage_role] = (pt + tokens, pm + micro)

    since_bound = min((row.timestamp for row in rows if row.timestamp), default=None)
    until_bound = max((row.timestamp for row in rows if row.timestamp), default=None)

    for share_key in share_buckets:
        if share_key in share_run_count:
            continue
        agent_id, scenario_id, _model = share_key
        share_run_count[share_key] = _count_results_in_share_scope(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            scenario_id=scenario_id,
            since=since_bound,
            until=until_bound,
        )

    page_ids = {str(row.id) for row in rows}

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

    for row in usage_query.all():
        if _share_key_from_row(row) is not None:
            continue
        ctx = row.context if isinstance(row.context, dict) else {}
        if _parse_uuid(ctx.get("evaluator_result_id")):
            continue
        matched_ids = _result_ids_for_usage_row(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            row=row,
            since=since_bound,
            until=until_bound,
        )
        matched_ids = [rid for rid in matched_ids if str(rid) in page_ids]
        if not matched_ids:
            continue
        tokens = _row_token_total(row)
        micro = int(row.total_cost_micro_usd or 0)
        if tokens <= 0 and micro <= 0:
            continue
        model_name = (row.model or "").strip() or "Unknown model"
        usage_role = _role_key_from_usage_row(row)
        share_tokens = tokens // len(matched_ids)
        share_micro = micro // len(matched_ids)
        for result_id in matched_ids:
            result_key = str(result_id)
            prev_tokens, prev_micro = totals[result_key]
            totals[result_key] = (prev_tokens + share_tokens, prev_micro + share_micro)
            model_bucket = by_model[result_key]
            prev_m_tokens, prev_m_micro = model_bucket.get(model_name, (0, 0))
            model_bucket[model_name] = (prev_m_tokens + share_tokens, prev_m_micro + share_micro)
            _add_role_slice(by_role, result_key, usage_role, share_tokens, share_micro)

    return (
        dict(totals),
        {key: dict(value) for key, value in by_model.items()},
        {key: dict(value) for key, value in by_role.items()},
    )


def _usage_row_matches_playground_mode(row: LLMUsageDaily, playground: Optional[bool]) -> bool:
    if playground is None:
        return True
    section = row.product_section or ""
    live = section in LIVE_USAGE_SECTIONS
    return playground == live


def evaluator_result_ids_with_usage_model(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    model: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    playground: Optional[bool] = None,
) -> List[UUID]:
    model_key = (model or "").strip()
    if not model_key:
        return []
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

    out: set[UUID] = set()
    for row in usage_query.all():
        if not _usage_row_matches_playground_mode(row, playground):
            continue
        for result_id in _result_ids_for_usage_row(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            row=row,
            since=since,
            until=until,
        ):
            out.add(result_id)
    return list(out)


def usage_enrichment_caches_for_results(
    db: Session,
    results: Iterable[EvaluatorResult],
    *,
    usage_since: Optional[date] = None,
    usage_until: Optional[date] = None,
) -> Tuple[
    Dict[UUID, CallRecording],
    Dict[str, Tuple[int, int]],
    Dict[str, Dict[str, Tuple[int, int]]],
    Dict[str, Dict[str, Tuple[int, int]]],
]:
    rows = list(results)
    if not rows:
        return {}, {}, {}, {}
    organization_id = rows[0].organization_id
    workspace_id = rows[0].workspace_id
    result_ids = [row.id for row in rows]
    recordings = batch_recordings_for_evaluator_results(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        result_ids=result_ids,
    )
    rollups, rollups_by_model, rollups_by_role = batch_llm_usage_rollups_for_results(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        results=rows,
        usage_since=usage_since,
        usage_until=usage_until,
    )
    return recordings, rollups, rollups_by_model, rollups_by_role