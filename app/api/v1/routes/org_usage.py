"""Org-scoped LLM Usage API (tokens + call counts)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from app.services.usage.access import UsageAccessPolicy
from app.services.usage.dates import usage_date_filter_bounds, usage_local_today
from typing import Any, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, cast, func, or_, select, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_organization_id
from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportTag,
    CallImportTagAssignment,
    Agent,
    LLMUsageDaily,
    Workspace,
)
from app.services.usage.read_cache import (
    acquire_read_lock,
    cache_key_for,
    cache_ttl_seconds,
    get_cached_response,
    get_stale_response,
    read_cache_version,
    release_read_lock,
    set_cached_response,
    wait_for_cached_response,
)
from app.services.usage.fx_rates import get_usd_inr_rate
from app.services.usage.usage_costs import costs_from_micro
from app.services.usage.usage_labels import (
    labels_for_call_import_ids,
    labels_for_resource_buckets,
    usage_kind_label,
    UsageNameResolver,
    parse_uuid,
)

router = APIRouter(prefix="/organizations/usage", tags=["Usage"])

GroupBy = Literal[
    "workspace",
    "product_section",
    "model",
    "resource",
    "usage_kind",
    "call_import",
]

SECTION_LABELS = {
    "call_import_evaluations": "Call Import Evaluations",
    "call_imports": "Call Imports",
    "playground": "Playground",
    "voice_playground": "Voice Playground",
    "evaluators": "Evaluators",
    "metrics": "Metrics",
    "chat": "Chat",
    "judge_alignment": "Judge Alignment",
    "prompt_optimization": "Prompt Optimization",
    "personas": "Personas",
    "agents": "Agents",
    "prompt_partials": "Prompt Partials",
    "conversation_evaluations": "Conversation Evaluations",
    "telephony": "Telephony",
    "test_agent": "Test Agent",
    "other": "Other",
}

_FILTER_OPTION_LIMIT = 500
_UUID_RE = (
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    "[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _usage_row_weight():
    return (
        LLMUsageDaily.prompt_tokens
        + LLMUsageDaily.completion_tokens
        + LLMUsageDaily.cache_read_tokens
        + LLMUsageDaily.cache_creation_tokens
        + LLMUsageDaily.reasoning_tokens
        + LLMUsageDaily.audio_seconds
        + LLMUsageDaily.tts_characters
    )


class UsageCosts(BaseModel):
    input_cost_usd: float = 0
    output_cost_usd: float = 0
    cache_read_cost_usd: float = 0
    cache_write_cost_usd: float = 0
    reasoning_cost_usd: float = 0
    audio_cost_usd: float = 0
    tts_cost_usd: float = 0
    total_cost_usd: float = 0
    currency: str = "USD"
    has_unpriced_usage: bool = False


class UsageTotals(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0
    audio_seconds: int = 0
    tts_characters: int = 0
    call_count: int = 0
    input_cost_micro_usd: int = 0
    output_cost_micro_usd: int = 0
    cache_read_cost_micro_usd: int = 0
    cache_creation_cost_micro_usd: int = 0
    reasoning_cost_micro_usd: int = 0
    audio_cost_micro_usd: int = 0
    tts_cost_micro_usd: int = 0
    total_cost_micro_usd: int = 0
    costs: UsageCosts = Field(default_factory=UsageCosts)


class UsageFxRateResponse(BaseModel):
    base: str = "USD"
    quote: str = "INR"
    rate: float
    as_of: datetime
    source: str


class UsagePolicyMeta(BaseModel):
    extended_history: bool
    max_history_days: Optional[int] = None
    range_clamped: bool = False


class UsageSummaryResponse(BaseModel):
    start: date
    end: date
    totals: UsageTotals
    usage_policy: UsagePolicyMeta
    last_updated_at: Optional[datetime] = None


class UsageBreakdownRow(BaseModel):
    workspace_id: Optional[UUID] = None
    workspace_name: Optional[str] = None
    product_section: Optional[str] = None
    product_section_label: Optional[str] = None
    model: Optional[str] = None
    resource_id: Optional[UUID] = None
    resource_type: Optional[str] = None
    resource_label: Optional[str] = None
    call_import_id: Optional[UUID] = None
    call_import_label: Optional[str] = None
    usage_kind: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0
    audio_seconds: int = 0
    tts_characters: int = 0
    call_count: int = 0
    input_cost_micro_usd: int = 0
    output_cost_micro_usd: int = 0
    cache_read_cost_micro_usd: int = 0
    cache_creation_cost_micro_usd: int = 0
    reasoning_cost_micro_usd: int = 0
    audio_cost_micro_usd: int = 0
    tts_cost_micro_usd: int = 0
    total_cost_micro_usd: int = 0
    costs: UsageCosts = Field(default_factory=UsageCosts)


class UsageBreakdownResponse(BaseModel):
    start: date
    end: date
    group_by: GroupBy
    rows: List[UsageBreakdownRow]
    total_count: int
    truncated_at_limit: bool = False
    usage_policy: UsagePolicyMeta
    last_updated_at: Optional[datetime] = None


class UsageFiltersResponse(BaseModel):
    workspaces: List[dict] = Field(default_factory=list)
    product_sections: List[dict] = Field(default_factory=list)
    call_imports: List[dict] = Field(default_factory=list)
    evaluations: List[dict] = Field(default_factory=list)
    models: List[str] = Field(default_factory=list)
    resources: List[dict] = Field(default_factory=list)
    usage_kinds: List[dict] = Field(default_factory=list)
    datasets: List[str] = Field(default_factory=list)
    tags: List[dict] = Field(default_factory=list)


def _parse_usage_range(
    start: Optional[date],
    end: Optional[date],
    tz: Optional[str],
) -> tuple[date, date, date, date]:
    """Return display_start, display_end, filter_start, filter_end."""
    today = usage_local_today(tz)
    display_start = start or today
    display_end = end or today
    filter_start, filter_end = usage_date_filter_bounds(
        display_start, display_end, tz
    )
    return display_start, display_end, filter_start, filter_end


def _usage_range_is_historical(access) -> bool:
    """Closed in UTC. A timezone behind UTC can still be 'today' locally."""
    return access.filter_end < datetime.now(timezone.utc).date()


def _prepare_usage_read(organization_id, endpoint, cache_key, model):
    """Return a cached payload, or (None, leader, version) when this request should query.

    ``version`` is read before the database work so a flush during the query
    cannot store the old totals under the new cache epoch.
    """
    version = read_cache_version(organization_id)
    cached = get_cached_response(organization_id, endpoint, cache_key, version)
    if cached is not None:
        try:
            return model.model_validate(cached), False, version
        except Exception:
            pass
    if cache_ttl_seconds() <= 0:
        return None, False, version
    if acquire_read_lock(organization_id, endpoint, cache_key):
        return None, True, version
    stale = get_stale_response(organization_id, endpoint, cache_key)
    if stale is not None:
        try:
            return model.model_validate(stale), False, version
        except Exception:
            pass
    waited = wait_for_cached_response(organization_id, endpoint, cache_key)
    if waited is not None:
        try:
            return model.model_validate(waited), False, version
        except Exception:
            pass
    return None, False, version


def _usage_policy_meta(access) -> UsagePolicyMeta:
    return UsagePolicyMeta(
        extended_history=access.policy.extended_history,
        max_history_days=access.policy.max_history_days,
        range_clamped=access.range_clamped,
    )


def _evaluation_id_expr():
    return func.coalesce(
        LLMUsageDaily.context["evaluation_id"].astext,
        case(
            (
                LLMUsageDaily.context["resource_type"].astext
                == "call_import_evaluation",
                LLMUsageDaily.context["resource_id"].astext,
            ),
            else_=None,
        ),
    )


def _resource_id_expr():
    """Resource rollup key: explicit resource_id or agent_id fallback."""
    return func.coalesce(
        LLMUsageDaily.context["resource_id"].astext,
        LLMUsageDaily.context["agent_id"].astext,
    )


def _resource_type_expr():
    rid_expr = _resource_id_expr()
    return func.coalesce(
        LLMUsageDaily.context["resource_type"].astext,
        case(
            (LLMUsageDaily.context["agent_id"].astext.isnot(None), "agent"),
            (
                and_(
                    LLMUsageDaily.product_section == "agents",
                    rid_expr.isnot(None),
                ),
                "agent",
            ),
            else_=None,
        ),
    )


def _direct_call_import_id_expr():
    """Call import id already stored on the rollup. No per-row joins."""
    return cast(
        func.coalesce(
            LLMUsageDaily.context["call_import_id"].astext,
            case(
                (
                    LLMUsageDaily.context["resource_type"].astext == "call_import",
                    LLMUsageDaily.context["resource_id"].astext,
                ),
                else_=None,
            ),
        ),
        String,
    )


def _evaluation_id_for_import_expr():
    """Evaluation id used to resolve a call import in one catalog lookup."""
    return cast(
        func.coalesce(
            _evaluation_id_expr(),
            case(
                (
                    LLMUsageDaily.context["resource_type"].astext
                    == "call_import_evaluation",
                    LLMUsageDaily.context["resource_id"].astext,
                ),
                else_=None,
            ),
        ),
        String,
    )


def _resource_scope_filter(resource_id: UUID):
    """Match usage attributed to a product resource (agent, simulation, etc.)."""
    rid = str(resource_id)
    return or_(
        LLMUsageDaily.context["resource_id"].astext == rid,
        LLMUsageDaily.context["agent_id"].astext == rid,
    )


def _evaluation_scope_filter(
    evaluation_id: UUID,
    organization_id: UUID,
    db: Session,
):
    """Match an evaluation from indexed context keys.

    Legacy ``evaluation_row_id`` values are copied onto ``evaluation_id`` by
    migration 119, so this does not scan call-import row tables.
    """
    del organization_id, db
    eid = str(evaluation_id)
    return or_(
        LLMUsageDaily.context["evaluation_id"].astext == eid,
        and_(
            LLMUsageDaily.context["resource_id"].astext == eid,
            LLMUsageDaily.context["resource_type"].astext == "call_import_evaluation",
        ),
    )


def _call_import_scope_filter(
    call_import_id: UUID,
    organization_id: UUID,
    db: Session,
):
    """Match usage tied to a call import or one of its evaluations."""
    del db
    cid = str(call_import_id)
    eval_ids = select(cast(CallImportEvaluation.id, String)).where(
        CallImportEvaluation.organization_id == organization_id,
        CallImportEvaluation.call_import_id == call_import_id,
    )
    return or_(
        LLMUsageDaily.context["call_import_id"].astext == cid,
        and_(
            LLMUsageDaily.context["resource_id"].astext == cid,
            LLMUsageDaily.context["resource_type"].astext == "call_import",
        ),
        LLMUsageDaily.context["evaluation_id"].astext.in_(eval_ids),
        and_(
            LLMUsageDaily.context["resource_id"].astext.in_(eval_ids),
            LLMUsageDaily.context["resource_type"].astext == "call_import_evaluation",
        ),
    )


def _scoped_call_import_id_select(
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID] = None,
    dataset: Optional[str] = None,
    tag_id: Optional[UUID] = None,
):
    """Call-import ids for dataset/tag scope. Stays a SQL subquery — never a Python list."""
    stmt = select(CallImport.id).where(CallImport.organization_id == organization_id)
    if workspace_id is not None:
        stmt = stmt.where(CallImport.workspace_id == workspace_id)
    if dataset:
        stmt = stmt.where(CallImport.dataset == dataset)
    if tag_id is not None:
        stmt = stmt.where(
            CallImport.id.in_(
                select(CallImportTagAssignment.call_import_id).where(
                    CallImportTagAssignment.tag_id == tag_id
                )
            )
        )
    return stmt


def _call_import_ids_scope_filter(import_id_select):
    allowed = select(cast(CallImport.id, String)).where(CallImport.id.in_(import_id_select))
    eval_ids = select(cast(CallImportEvaluation.id, String)).where(
        CallImportEvaluation.call_import_id.in_(import_id_select)
    )
    return or_(
        _direct_call_import_id_expr().in_(allowed),
        _evaluation_id_for_import_expr().in_(eval_ids),
    )


def _workspace_scope_filter(
    workspace_id: UUID,
    organization_id: UUID,
):
    """Match workspace-scoped rows plus legacy call-import usage with null workspace_id."""
    ws_call_import_ids = (
        select(cast(CallImport.id, String))
        .where(
            CallImport.organization_id == organization_id,
            CallImport.workspace_id == workspace_id,
        )
    )
    ws_eval_ids = (
        select(cast(CallImportEvaluation.id, String)).where(
            CallImportEvaluation.organization_id == organization_id,
            CallImportEvaluation.workspace_id == workspace_id,
        )
    )
    legacy_call_import = and_(
        LLMUsageDaily.workspace_id.is_(None),
        or_(
            _direct_call_import_id_expr().in_(ws_call_import_ids),
            _evaluation_id_for_import_expr().in_(ws_eval_ids),
        ),
    )
    return or_(LLMUsageDaily.workspace_id == workspace_id, legacy_call_import)


def _apply_filters(
    query,
    *,
    organization_id: UUID,
    start: date,
    end: date,
    enforced_floor: Optional[date] = None,
    workspace_id: Optional[UUID],
    product_section: Optional[str],
    model: Optional[str],
    resource_id: Optional[UUID],
    usage_kind: Optional[str] = None,
    call_import_id: Optional[UUID] = None,
    evaluation_id: Optional[UUID] = None,
    evaluation_row_id: Optional[UUID] = None,
    dataset: Optional[str] = None,
    tag_id: Optional[UUID] = None,
    db: Optional[Session] = None,
):
    effective_start = start
    if enforced_floor is not None and effective_start < enforced_floor:
        effective_start = enforced_floor
    query = query.filter(
        LLMUsageDaily.organization_id == organization_id,
        LLMUsageDaily.usage_date >= effective_start,
        LLMUsageDaily.usage_date <= end,
    )
    if workspace_id is not None:
        query = query.filter(
            _workspace_scope_filter(workspace_id, organization_id)
        )
    if product_section:
        query = query.filter(LLMUsageDaily.product_section == product_section)
    if model:
        query = query.filter(LLMUsageDaily.model == model)
    if resource_id is not None:
        rid_filter = _resource_scope_filter(resource_id)
        if db is not None:
            query = query.filter(
                or_(
                    _evaluation_scope_filter(resource_id, organization_id, db),
                    rid_filter,
                )
            )
        else:
            query = query.filter(
                or_(
                    LLMUsageDaily.context["resource_id"].astext == str(resource_id),
                    LLMUsageDaily.context["agent_id"].astext == str(resource_id),
                    LLMUsageDaily.context["evaluation_id"].astext == str(resource_id),
                    LLMUsageDaily.context["evaluation_row_id"].astext == str(resource_id),
                )
            )
    if call_import_id is not None:
        if db is not None:
            query = query.filter(
                _call_import_scope_filter(call_import_id, organization_id, db)
            )
        else:
            query = query.filter(
                LLMUsageDaily.context["call_import_id"].astext == str(call_import_id)
            )
    if evaluation_id is not None and evaluation_id != resource_id:
        if db is not None:
            query = query.filter(
                _evaluation_scope_filter(evaluation_id, organization_id, db)
            )
        else:
            query = query.filter(
                LLMUsageDaily.context["evaluation_id"].astext == str(evaluation_id)
            )
    if evaluation_row_id is not None:
        query = query.filter(
            LLMUsageDaily.context["evaluation_row_id"].astext
            == str(evaluation_row_id)
        )
    if usage_kind:
        query = query.filter(LLMUsageDaily.usage_kind == usage_kind)
    if dataset or tag_id is not None:
        if db is None:
            raise ValueError("db required for dataset/tag filters")
        query = query.filter(
            _call_import_ids_scope_filter(
                _scoped_call_import_id_select(
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    dataset=dataset,
                    tag_id=tag_id,
                )
            )
        )
    return query


def _filtered_query(
    db: Session,
    *,
    organization_id: UUID,
    start: date,
    end: date,
    enforced_floor: Optional[date] = None,
    workspace_id: Optional[UUID] = None,
    product_section: Optional[str] = None,
    model: Optional[str] = None,
    resource_id: Optional[UUID] = None,
    usage_kind: Optional[str] = None,
    call_import_id: Optional[UUID] = None,
    evaluation_id: Optional[UUID] = None,
    evaluation_row_id: Optional[UUID] = None,
    dataset: Optional[str] = None,
    tag_id: Optional[UUID] = None,
):
    return _apply_filters(
        db.query(LLMUsageDaily),
        organization_id=organization_id,
        start=start,
        end=end,
        enforced_floor=enforced_floor,
        workspace_id=workspace_id,
        product_section=product_section,
        model=model,
        resource_id=resource_id,
        usage_kind=usage_kind,
        call_import_id=call_import_id,
        evaluation_id=evaluation_id,
        evaluation_row_id=evaluation_row_id,
        dataset=dataset,
        tag_id=tag_id,
        db=db,
    )


def _infer_agent_types_for_label_buckets(
    db: Session,
    organization_id: UUID,
    grouped: dict[str, tuple[Optional[str], list]],
) -> None:
    """When context JSON omits resource_type, infer agent rows from Agent.id."""
    candidate_ids: list[UUID] = []
    for rid, (rtype, _) in grouped.items():
        if rtype:
            continue
        uid = parse_uuid(rid)
        if uid:
            candidate_ids.append(uid)
    if not candidate_ids:
        return
    known_agent_ids = {
        row.id
        for row in db.query(Agent.id).filter(
            Agent.organization_id == organization_id,
            Agent.id.in_(candidate_ids),
        ).all()
    }
    for rid in grouped:
        uid = parse_uuid(rid)
        if uid and uid in known_agent_ids:
            rtype, contexts = grouped[rid]
            if not rtype:
                grouped[rid] = ("agent", contexts)


def _resource_labels_for_ids(
    db: Session,
    organization_id: UUID,
    query,
    resource_ids: List[str],
) -> dict[str, str]:
    """Label only the resource ids already returned by the breakdown page."""
    if not resource_ids:
        return {}
    rid = cast(_resource_id_expr(), String)
    rows = (
        query.with_entities(rid, _resource_type_expr(), LLMUsageDaily.context)
        .filter(rid.in_(resource_ids))
        .distinct(rid)
        .order_by(rid, _usage_row_weight().desc())
        .all()
    )
    grouped: dict[str, tuple[Optional[str], list]] = {}
    for raw_id, rtype, ctx in rows:
        if not raw_id:
            continue
        grouped[str(raw_id)] = (rtype, [dict(ctx or {})])
    _infer_agent_types_for_label_buckets(db, organization_id, grouped)
    buckets = [(key, rtype, contexts) for key, (rtype, contexts) in grouped.items()]
    resolver = UsageNameResolver(db, organization_id)
    contexts_for_preload = []
    for key, rtype, contexts in buckets:
        for ctx in contexts:
            merged = dict(ctx or {})
            merged.setdefault("resource_id", key)
            if rtype:
                merged.setdefault("resource_type", rtype)
            contexts_for_preload.append(merged)
    resolver.preload(contexts_for_preload)
    return labels_for_resource_buckets(buckets, resolver)


def _breakdown_resource_label(
    raw_res_id: Optional[str],
    res_type: Optional[str],
    section: Optional[str],
    resource_labels: dict[str, str],
    db: Session,
    organization_id: UUID,
) -> str:
    if not raw_res_id:
        return "Unscoped"
    key = str(raw_res_id)
    label = resource_labels.get(key)
    if label and label != "Unscoped":
        return label
    effective_type = res_type or ("agent" if section == "agents" else None)
    if effective_type == "agent":
        resolver = UsageNameResolver(db, organization_id)
        resolver.preload([{"resource_id": key, "resource_type": "agent"}])
        return resolver.agent_name(key)
    return label or "Unscoped"


def _call_import_ids_for_usage_query(
    db: Session,
    organization_id: UUID,
    query,
) -> set[UUID]:
    """Resolve call import ids from rollup context, then one catalog evaluation lookup."""
    direct = _direct_call_import_id_expr()
    evaluation = _evaluation_id_for_import_expr()
    rows = (
        query.with_entities(direct, evaluation)
        .group_by(direct, evaluation)
        .order_by(func.sum(_usage_row_weight()).desc())
        .limit(_FILTER_OPTION_LIMIT)
        .all()
    )
    import_ids: set[UUID] = set()
    eval_ids: set[UUID] = set()
    for direct_raw, eval_raw in rows:
        direct_id = parse_uuid(direct_raw)
        if direct_id:
            import_ids.add(direct_id)
            continue
        eval_id = parse_uuid(eval_raw)
        if eval_id:
            eval_ids.add(eval_id)
    if eval_ids:
        for row in (
            db.query(CallImportEvaluation.call_import_id)
            .filter(
                CallImportEvaluation.organization_id == organization_id,
                CallImportEvaluation.id.in_(eval_ids),
            )
            .all()
        ):
            import_ids.add(row[0])
    return import_ids


def _call_import_filter_labels(
    db: Session,
    organization_id: UUID,
    query,
    workspace_id: Optional[UUID] = None,
    dataset: Optional[str] = None,
    tag_id: Optional[UUID] = None,
    call_import_id: Optional[UUID] = None,
) -> dict[str, str]:
    """Call imports for filters: heaviest usage in range, plus recent workspace imports."""
    import_ids = _call_import_ids_for_usage_query(db, organization_id, query)

    if workspace_id is not None:
        recent = (
            db.query(CallImport.id)
            .filter(
                CallImport.id.in_(
                    _scoped_call_import_id_select(
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        dataset=dataset,
                        tag_id=tag_id,
                    )
                )
            )
            .order_by(CallImport.created_at.desc())
            .limit(_FILTER_OPTION_LIMIT)
            .all()
        )
        import_ids.update(row[0] for row in recent)
    if call_import_id is not None:
        import_ids.add(call_import_id)

    if not import_ids:
        return {}
    resolver = UsageNameResolver(db, organization_id)
    resolver.preload([{"call_import_id": str(uid)} for uid in import_ids])
    return labels_for_call_import_ids(list(import_ids), resolver)


def _unpriced_usage_condition():
    return and_(
        LLMUsageDaily.pricing_rate_id.is_(None),
        _usage_row_weight() > 0,
    )


def _has_unpriced_usage_column():
    return func.coalesce(func.bool_or(_unpriced_usage_condition()), False).label(
        "has_unpriced_usage"
    )


def _usage_cost_sum_columns():
    return (
        func.coalesce(func.sum(LLMUsageDaily.input_cost_micro_usd), 0).label(
            "input_cost_micro_usd"
        ),
        func.coalesce(func.sum(LLMUsageDaily.output_cost_micro_usd), 0).label(
            "output_cost_micro_usd"
        ),
        func.coalesce(func.sum(LLMUsageDaily.cache_read_cost_micro_usd), 0).label(
            "cache_read_cost_micro_usd"
        ),
        func.coalesce(func.sum(LLMUsageDaily.cache_creation_cost_micro_usd), 0).label(
            "cache_creation_cost_micro_usd"
        ),
        func.coalesce(func.sum(LLMUsageDaily.reasoning_cost_micro_usd), 0).label(
            "reasoning_cost_micro_usd"
        ),
        func.coalesce(func.sum(LLMUsageDaily.audio_cost_micro_usd), 0).label(
            "audio_cost_micro_usd"
        ),
        func.coalesce(func.sum(LLMUsageDaily.tts_cost_micro_usd), 0).label(
            "tts_cost_micro_usd"
        ),
        func.coalesce(func.sum(LLMUsageDaily.total_cost_micro_usd), 0).label(
            "total_cost_micro_usd"
        ),
    )


def _attach_costs(metrics: dict, *, has_unpriced_usage: bool = False) -> dict:
    costs = costs_from_micro(
        input_cost_micro_usd=metrics.get("input_cost_micro_usd", 0),
        output_cost_micro_usd=metrics.get("output_cost_micro_usd", 0),
        cache_read_cost_micro_usd=metrics.get("cache_read_cost_micro_usd", 0),
        cache_creation_cost_micro_usd=metrics.get("cache_creation_cost_micro_usd", 0),
        reasoning_cost_micro_usd=metrics.get("reasoning_cost_micro_usd", 0),
        audio_cost_micro_usd=metrics.get("audio_cost_micro_usd", 0),
        tts_cost_micro_usd=metrics.get("tts_cost_micro_usd", 0),
        total_cost_micro_usd=metrics.get("total_cost_micro_usd", 0),
        has_unpriced_usage=has_unpriced_usage,
    )
    return {**metrics, "costs": costs}


def _usage_totals_from_row(row) -> dict:
    prompt = int(row.prompt_tokens)
    completion = int(row.completion_tokens)
    metrics = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cache_read_tokens": int(row.cache_read_tokens),
        "cache_creation_tokens": int(row.cache_creation_tokens),
        "reasoning_tokens": int(row.reasoning_tokens),
        "audio_seconds": int(row.audio_seconds),
        "tts_characters": int(row.tts_characters),
        "call_count": int(row.call_count),
        "input_cost_micro_usd": int(getattr(row, "input_cost_micro_usd", 0) or 0),
        "output_cost_micro_usd": int(getattr(row, "output_cost_micro_usd", 0) or 0),
        "cache_read_cost_micro_usd": int(
            getattr(row, "cache_read_cost_micro_usd", 0) or 0
        ),
        "cache_creation_cost_micro_usd": int(
            getattr(row, "cache_creation_cost_micro_usd", 0) or 0
        ),
        "reasoning_cost_micro_usd": int(
            getattr(row, "reasoning_cost_micro_usd", 0) or 0
        ),
        "audio_cost_micro_usd": int(getattr(row, "audio_cost_micro_usd", 0) or 0),
        "tts_cost_micro_usd": int(getattr(row, "tts_cost_micro_usd", 0) or 0),
        "total_cost_micro_usd": int(getattr(row, "total_cost_micro_usd", 0) or 0),
    }
    return _attach_costs(
        metrics,
        has_unpriced_usage=bool(getattr(row, "has_unpriced_usage", False)),
    )


def _breakdown_sort_exprs():
    """Highest token volume first, then calls, then cost. Matches the UI sort."""
    tokens = func.sum(LLMUsageDaily.prompt_tokens + LLMUsageDaily.completion_tokens)
    return (
        tokens.desc(),
        func.sum(LLMUsageDaily.call_count).desc(),
        func.sum(LLMUsageDaily.total_cost_micro_usd).desc(),
    )


def _filters_share_facet_scan(
    *,
    workspace_id: Optional[UUID],
    product_section: Optional[str],
    model: Optional[str],
    resource_id: Optional[UUID],
    usage_kind: Optional[str],
    call_import_id: Optional[UUID],
    evaluation_id: Optional[UUID],
) -> bool:
    """Workspace, section, kind, and model lists scan the same rows when unscoped."""
    return not any(
        (
            workspace_id,
            product_section,
            model,
            resource_id,
            usage_kind,
            call_import_id,
            evaluation_id,
        )
    )


def _facet_sets(query) -> tuple[set, set, set, set]:
    rows = (
        query.with_entities(
            LLMUsageDaily.workspace_id,
            LLMUsageDaily.product_section,
            LLMUsageDaily.usage_kind,
            LLMUsageDaily.model,
        )
        .distinct()
        .all()
    )
    workspace_ids: set = set()
    sections: set = set()
    kinds: set = set()
    models: set = set()
    for workspace_id, section, kind, model_name in rows:
        if workspace_id is not None:
            workspace_ids.add(workspace_id)
        if section:
            sections.add(section)
        if kind:
            kinds.add(kind)
        if model_name:
            models.add(model_name)
    return workspace_ids, sections, kinds, models


def _grouped_resource_filter_rows(
    query,
    extra_resource_ids: Optional[List[str]] = None,
):
    """Top resources by usage, then one context JSON each."""
    resource_id = cast(_resource_id_expr(), String)
    ranked = (
        query.with_entities(
            resource_id,
            func.max(cast(_resource_type_expr(), String)),
            func.max(LLMUsageDaily.product_section),
            func.max(LLMUsageDaily.context["evaluation_id"].astext),
        )
        .filter(resource_id.isnot(None))
        .group_by(resource_id)
        .order_by(func.sum(_usage_row_weight()).desc())
        .limit(_FILTER_OPTION_LIMIT)
        .all()
    )
    by_id: dict[str, tuple] = {}
    for row in ranked:
        if row[0]:
            by_id[str(row[0])] = row
    for extra in extra_resource_ids or []:
        if not extra or extra in by_id:
            continue
        extra_row = (
            query.with_entities(
                resource_id,
                func.max(cast(_resource_type_expr(), String)),
                func.max(LLMUsageDaily.product_section),
                func.max(LLMUsageDaily.context["evaluation_id"].astext),
            )
            .filter(resource_id == extra)
            .group_by(resource_id)
            .first()
        )
        if extra_row and extra_row[0]:
            by_id[str(extra_row[0])] = extra_row
    if not by_id:
        return []
    contexts: dict[str, Any] = {}
    for raw_id, ctx in (
        query.with_entities(resource_id, LLMUsageDaily.context)
        .filter(resource_id.in_(list(by_id)))
        .distinct(resource_id)
        .order_by(resource_id, _usage_row_weight().desc())
        .all()
    ):
        if raw_id:
            contexts[str(raw_id)] = ctx
    return [
        (key, row[1], row[2], row[3], contexts.get(key))
        for key, row in by_id.items()
    ]


def _resource_filter_bundle(
    db: Session,
    organization_id: UUID,
    query,
    extra_resource_ids: Optional[List[str]] = None,
) -> tuple[dict[str, str], dict[str, dict[str, Optional[str]]], dict[str, str]]:
    """Labels, resource meta, and evaluation labels from one grouped scan."""
    grouped: dict[str, tuple[Optional[str], list]] = {}
    meta: dict[str, dict[str, Optional[str]]] = {}
    eval_grouped: dict[str, tuple[Optional[str], list]] = {}
    for raw_id, rtype, section, eval_id, context in _grouped_resource_filter_rows(
        query, extra_resource_ids=extra_resource_ids
    ):
        if not raw_id:
            continue
        key = str(raw_id)
        ctx = dict(context or {})
        if key not in grouped:
            grouped[key] = (rtype, [])
        grouped[key][1].append(ctx)
        entry = meta.setdefault(key, {"type": None, "product_section": None})
        if rtype:
            entry["type"] = str(rtype)
        if section:
            entry["product_section"] = str(section)
        if not entry["type"] and section == "agents":
            entry["type"] = "agent"
        eval_key = eval_id or ctx.get("evaluation_id")
        if not eval_key and rtype == "call_import_evaluation":
            eval_key = key
        if eval_key:
            eval_bucket = eval_grouped.setdefault(str(eval_key), (rtype, []))
            eval_bucket[1].append(ctx)

    _infer_agent_types_for_label_buckets(db, organization_id, grouped)
    buckets = [(rid, rtype, contexts) for rid, (rtype, contexts) in grouped.items()]
    resolver = UsageNameResolver(db, organization_id)
    contexts_for_preload = []
    for rid, rtype, contexts in buckets:
        for ctx in contexts:
            merged = dict(ctx or {})
            if rid:
                merged.setdefault("resource_id", rid)
            if rtype:
                merged.setdefault("resource_type", rtype)
            contexts_for_preload.append(merged)
    for rtype, contexts in eval_grouped.values():
        for ctx in contexts:
            merged = dict(ctx or {})
            if rtype and "resource_type" not in merged:
                merged["resource_type"] = rtype
            contexts_for_preload.append(merged)
    resolver.preload(contexts_for_preload)
    resource_labels = labels_for_resource_buckets(buckets, resolver)
    evaluation_labels = {
        raw_id: resolver.evaluation_name(
            str((contexts[0] or {}).get("evaluation_id") or raw_id)
        )
        for raw_id, (_rtype, contexts) in eval_grouped.items()
    }
    return resource_labels, meta, evaluation_labels


def _breakdown_metrics_from_tuple(metrics: tuple) -> dict:
    prompt = int(metrics[0])
    completion = int(metrics[1])
    base = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cache_read_tokens": int(metrics[2]),
        "cache_creation_tokens": int(metrics[3]),
        "reasoning_tokens": int(metrics[4]),
        "audio_seconds": int(metrics[5]),
        "tts_characters": int(metrics[6]),
        "call_count": int(metrics[7]),
        "input_cost_micro_usd": int(metrics[8]),
        "output_cost_micro_usd": int(metrics[9]),
        "cache_read_cost_micro_usd": int(metrics[10]),
        "cache_creation_cost_micro_usd": int(metrics[11]),
        "reasoning_cost_micro_usd": int(metrics[12]),
        "audio_cost_micro_usd": int(metrics[13]),
        "tts_cost_micro_usd": int(metrics[14]),
        "total_cost_micro_usd": int(metrics[15]),
    }
    has_unpriced = bool(metrics[16]) if len(metrics) > 16 else False
    return _attach_costs(base, has_unpriced_usage=has_unpriced)


def _last_updated(db: Session, organization_id: UUID) -> Optional[datetime]:
    return (
        db.query(LLMUsageDaily.updated_at)
        .filter(
            LLMUsageDaily.organization_id == organization_id,
            LLMUsageDaily.updated_at.isnot(None),
        )
        .order_by(LLMUsageDaily.updated_at.desc())
        .limit(1)
        .scalar()
    )


def _summary_aggregate_query(
    db: Session,
    *,
    organization_id: UUID,
    start: date,
    end: date,
    enforced_floor: Optional[date] = None,
    workspace_id: Optional[UUID],
    product_section: Optional[str],
    model: Optional[str],
    resource_id: Optional[UUID],
    usage_kind: Optional[str],
    call_import_id: Optional[UUID],
    evaluation_id: Optional[UUID],
    evaluation_row_id: Optional[UUID],
    dataset: Optional[str] = None,
    tag_id: Optional[UUID] = None,
):
    return _apply_filters(
        db.query(
            func.coalesce(func.sum(LLMUsageDaily.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LLMUsageDaily.completion_tokens), 0).label(
                "completion_tokens"
            ),
            func.coalesce(func.sum(LLMUsageDaily.cache_read_tokens), 0).label(
                "cache_read_tokens"
            ),
            func.coalesce(func.sum(LLMUsageDaily.cache_creation_tokens), 0).label(
                "cache_creation_tokens"
            ),
            func.coalesce(func.sum(LLMUsageDaily.reasoning_tokens), 0).label(
                "reasoning_tokens"
            ),
            func.coalesce(func.sum(LLMUsageDaily.audio_seconds), 0).label("audio_seconds"),
            func.coalesce(func.sum(LLMUsageDaily.tts_characters), 0).label("tts_characters"),
            func.coalesce(func.sum(LLMUsageDaily.call_count), 0).label("call_count"),
            *_usage_cost_sum_columns(),
            _has_unpriced_usage_column(),
        ),
        organization_id=organization_id,
        start=start,
        end=end,
        enforced_floor=enforced_floor,
        workspace_id=workspace_id,
        product_section=product_section,
        model=model,
        resource_id=resource_id,
        usage_kind=usage_kind,
        call_import_id=call_import_id,
        evaluation_id=evaluation_id,
        evaluation_row_id=evaluation_row_id,
        dataset=dataset,
        tag_id=tag_id,
        db=db,
    )


@router.get("/fx-rate", response_model=UsageFxRateResponse)
def get_usage_fx_rate():
    payload = get_usd_inr_rate()
    return UsageFxRateResponse(
        base=payload["base"],
        quote=payload["quote"],
        rate=float(payload["rate"]),
        as_of=datetime.fromisoformat(payload["as_of"]),
        source=payload["source"],
    )


@router.get("/summary", response_model=UsageSummaryResponse)
def get_usage_summary(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    tz: Optional[str] = Query(
        None,
        description="IANA timezone for interpreting start/end calendar dates",
    ),
    workspace_id: Optional[UUID] = Query(None),
    product_section: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    resource_id: Optional[UUID] = Query(None),
    usage_kind: Optional[str] = Query(None),
    call_import_id: Optional[UUID] = Query(None),
    evaluation_id: Optional[UUID] = Query(None),
    evaluation_row_id: Optional[UUID] = Query(None),
    dataset: Optional[str] = Query(None),
    tag_id: Optional[UUID] = Query(None),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    access = UsageAccessPolicy.resolve(organization_id, start, end, tz)
    display_start = access.display_start
    display_end = access.display_end
    if display_end < display_start:
        raise HTTPException(status_code=400, detail="end must be >= start")

    cache_key = cache_key_for(
        access,
        workspace_id=workspace_id,
        product_section=product_section,
        model=model,
        resource_id=resource_id,
        usage_kind=usage_kind,
        call_import_id=call_import_id,
        evaluation_id=evaluation_id,
        evaluation_row_id=evaluation_row_id,
        dataset=dataset,
        tag_id=tag_id,
    )
    cached_response, cache_leader, cache_version = _prepare_usage_read(
        organization_id, "summary", cache_key, UsageSummaryResponse
    )
    if cached_response is not None:
        return cached_response

    try:
        row = _summary_aggregate_query(
            db,
            organization_id=organization_id,
            start=access.filter_start,
            end=access.filter_end,
            enforced_floor=access.enforced_filter_floor,
            workspace_id=workspace_id,
            product_section=product_section,
            model=model,
            resource_id=resource_id,
            usage_kind=usage_kind,
            call_import_id=call_import_id,
            evaluation_id=evaluation_id,
            evaluation_row_id=evaluation_row_id,
            dataset=dataset,
            tag_id=tag_id,
        ).one()
        totals = _usage_totals_from_row(row)
        response = UsageSummaryResponse(
            start=display_start,
            end=display_end,
            totals=UsageTotals(**totals),
            usage_policy=_usage_policy_meta(access),
            last_updated_at=_last_updated(db, organization_id),
        )
        set_cached_response(
            organization_id,
            "summary",
            cache_key,
            response.model_dump(mode="json"),
            historical=_usage_range_is_historical(access),
            version=cache_version,
        )
        return response
    finally:
        if cache_leader:
            release_read_lock(organization_id, "summary", cache_key)


@router.get("/breakdown", response_model=UsageBreakdownResponse)
def get_usage_breakdown(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    tz: Optional[str] = Query(
        None,
        description="IANA timezone for interpreting start/end calendar dates",
    ),
    group_by: GroupBy = Query("workspace"),
    workspace_id: Optional[UUID] = Query(None),
    product_section: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    resource_id: Optional[UUID] = Query(None),
    usage_kind: Optional[str] = Query(None),
    call_import_id: Optional[UUID] = Query(None),
    evaluation_id: Optional[UUID] = Query(None),
    evaluation_row_id: Optional[UUID] = Query(None),
    dataset: Optional[str] = Query(None),
    tag_id: Optional[UUID] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    access = UsageAccessPolicy.resolve(organization_id, start, end, tz)
    display_start = access.display_start
    display_end = access.display_end
    if display_end < display_start:
        raise HTTPException(status_code=400, detail="end must be >= start")

    cache_key = cache_key_for(
        access,
        group_by=group_by,
        workspace_id=workspace_id,
        product_section=product_section,
        model=model,
        resource_id=resource_id,
        usage_kind=usage_kind,
        call_import_id=call_import_id,
        evaluation_id=evaluation_id,
        evaluation_row_id=evaluation_row_id,
        dataset=dataset,
        tag_id=tag_id,
        limit=limit,
        offset=offset,
    )
    cached_response, cache_leader, cache_version = _prepare_usage_read(
        organization_id, "breakdown", cache_key, UsageBreakdownResponse
    )
    if cached_response is not None:
        return cached_response

    try:
        dims = {
            "workspace": LLMUsageDaily.workspace_id,
            "product_section": LLMUsageDaily.product_section,
            "model": LLMUsageDaily.model,
            "resource": cast(_resource_id_expr(), String),
            "usage_kind": LLMUsageDaily.usage_kind,
        }

        aggregates = [
            func.coalesce(func.sum(LLMUsageDaily.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LLMUsageDaily.completion_tokens), 0).label(
                "completion_tokens"
            ),
            func.coalesce(func.sum(LLMUsageDaily.cache_read_tokens), 0).label(
                "cache_read_tokens"
            ),
            func.coalesce(func.sum(LLMUsageDaily.cache_creation_tokens), 0).label(
                "cache_creation_tokens"
            ),
            func.coalesce(func.sum(LLMUsageDaily.reasoning_tokens), 0).label(
                "reasoning_tokens"
            ),
            func.coalesce(func.sum(LLMUsageDaily.audio_seconds), 0).label("audio_seconds"),
            func.coalesce(func.sum(LLMUsageDaily.tts_characters), 0).label("tts_characters"),
            func.coalesce(func.sum(LLMUsageDaily.call_count), 0).label("call_count"),
            *_usage_cost_sum_columns(),
            _has_unpriced_usage_column(),
        ]

        resolved_call_import = None
        if group_by == "call_import":
            direct_expr = _direct_call_import_id_expr()
            eval_expr = _evaluation_id_for_import_expr()
            resolved_call_import = func.coalesce(
                direct_expr, cast(CallImportEvaluation.call_import_id, String)
            )
            base_query = (
                db.query(resolved_call_import, *aggregates)
                .select_from(LLMUsageDaily)
                .outerjoin(
                    CallImportEvaluation,
                    and_(
                        direct_expr.is_(None),
                        eval_expr.op("~")(_UUID_RE),
                        CallImportEvaluation.id == cast(eval_expr, PG_UUID),
                        CallImportEvaluation.organization_id == organization_id,
                    ),
                )
            )
            group_cols = [resolved_call_import]
        else:
            dim = dims[group_by]
            select_cols = [dim]
            group_cols = [dim]
            if group_by == "resource":
                select_cols.append(cast(_resource_type_expr(), String))
                group_cols.append(cast(_resource_type_expr(), String))
                select_cols.append(LLMUsageDaily.product_section)
                group_cols.append(LLMUsageDaily.product_section)
            base_query = db.query(*select_cols, *aggregates)

        query = _apply_filters(
            base_query,
            organization_id=organization_id,
            start=access.filter_start,
            end=access.filter_end,
            enforced_floor=access.enforced_filter_floor,
            workspace_id=workspace_id,
            product_section=product_section,
            model=model,
            resource_id=resource_id,
            usage_kind=usage_kind,
            call_import_id=call_import_id,
            evaluation_id=evaluation_id,
            evaluation_row_id=evaluation_row_id,
            dataset=dataset,
            tag_id=tag_id,
            db=db,
        ).group_by(*group_cols)

        results = (
            query.order_by(*_breakdown_sort_exprs())
            .offset(offset)
            .limit(limit)
            .all()
        )
        fetched_count = len(results)

        workspace_names: dict = {}
        if group_by == "workspace":
            ws_ids = {r[0] for r in results if r[0] is not None}
            if ws_ids:
                workspace_names = {
                    w.id: w.name
                    for w in db.query(Workspace)
                    .filter(
                        Workspace.organization_id == organization_id,
                        Workspace.id.in_(ws_ids),
                    )
                    .all()
                }
        resource_labels: dict[str, str] = {}
        call_import_labels: dict[str, str] = {}
        if group_by == "resource":
            resource_ids = [str(row[0]) for row in results if row[0]]
            label_query = _filtered_query(
                db,
                organization_id=organization_id,
                start=access.filter_start,
                end=access.filter_end,
                enforced_floor=access.enforced_filter_floor,
                workspace_id=workspace_id,
                product_section=product_section,
                model=model,
                resource_id=resource_id,
                usage_kind=usage_kind,
                call_import_id=call_import_id,
                evaluation_id=evaluation_id,
                evaluation_row_id=evaluation_row_id,
            )
            resource_labels = _resource_labels_for_ids(
                db, organization_id, label_query, resource_ids
            )
        elif group_by == "call_import":
            import_ids = []
            for row in results:
                parsed = parse_uuid(row[0])
                if parsed:
                    import_ids.append(parsed)
            if import_ids:
                resolver = UsageNameResolver(db, organization_id)
                resolver.preload(
                    [{"call_import_id": str(uid)} for uid in import_ids]
                )
                call_import_labels = labels_for_call_import_ids(import_ids, resolver)

        rows: List[UsageBreakdownRow] = []
        for result in results:
            if group_by == "workspace":
                ws_id = result[0]
                metrics = result[1:]
                rows.append(
                    UsageBreakdownRow(
                        workspace_id=ws_id,
                        workspace_name=workspace_names.get(ws_id) if ws_id else "Unknown",
                        **_breakdown_metrics_from_tuple(metrics),
                    )
                )
            elif group_by == "product_section":
                section = result[0]
                metrics = result[1:]
                rows.append(
                    UsageBreakdownRow(
                        product_section=section,
                        product_section_label=SECTION_LABELS.get(section or "", section),
                        **_breakdown_metrics_from_tuple(metrics),
                    )
                )
            elif group_by == "model":
                model_name = result[0]
                metrics = result[1:]
                rows.append(
                    UsageBreakdownRow(
                        model=model_name,
                        **_breakdown_metrics_from_tuple(metrics),
                    )
                )
            elif group_by == "usage_kind":
                kind = result[0]
                metrics = result[1:]
                rows.append(
                    UsageBreakdownRow(
                        usage_kind=kind,
                        **_breakdown_metrics_from_tuple(metrics),
                    )
                )
            elif group_by == "call_import":
                raw_cid = result[0]
                metrics = result[1:]
                cid = None
                if raw_cid:
                    try:
                        cid = UUID(str(raw_cid))
                    except (ValueError, TypeError):
                        cid = None
                label = (
                    call_import_labels.get(str(raw_cid), "Unscoped")
                    if raw_cid
                    else "Unscoped"
                )
                rows.append(
                    UsageBreakdownRow(
                        call_import_id=cid,
                        call_import_label=label,
                        **_breakdown_metrics_from_tuple(metrics),
                    )
                )
            else:
                raw_res_id, res_type, section = result[0], result[1], result[2]
                metrics = result[3:]
                res_id = None
                if raw_res_id:
                    try:
                        res_id = UUID(str(raw_res_id))
                    except (ValueError, TypeError):
                        res_id = None
                rows.append(
                    UsageBreakdownRow(
                        resource_id=res_id,
                        resource_type=res_type or (
                            "agent" if section == "agents" and raw_res_id else None
                        ),
                        resource_label=_breakdown_resource_label(
                            raw_res_id,
                            res_type,
                            section,
                            resource_labels,
                            db,
                            organization_id,
                        ),
                        product_section=section,
                        product_section_label=SECTION_LABELS.get(section or "", section),
                        **_breakdown_metrics_from_tuple(metrics),
                    )
                )

        response = UsageBreakdownResponse(
            start=display_start,
            end=display_end,
            group_by=group_by,
            rows=rows,
            total_count=len(rows),
            truncated_at_limit=fetched_count >= limit,
            usage_policy=_usage_policy_meta(access),
            last_updated_at=_last_updated(db, organization_id),
        )
        set_cached_response(
            organization_id,
            "breakdown",
            cache_key,
            response.model_dump(mode="json"),
            historical=_usage_range_is_historical(access),
            version=cache_version,
        )
        return response
    finally:
        if cache_leader:
            release_read_lock(organization_id, "breakdown", cache_key)


@router.get("/filters", response_model=UsageFiltersResponse)
def get_usage_filters(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    tz: Optional[str] = Query(
        None,
        description="IANA timezone for interpreting start/end calendar dates",
    ),
    workspace_id: Optional[UUID] = Query(None),
    product_section: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    resource_id: Optional[UUID] = Query(None),
    usage_kind: Optional[str] = Query(None),
    call_import_id: Optional[UUID] = Query(None),
    evaluation_id: Optional[UUID] = Query(None),
    dataset: Optional[str] = Query(None),
    tag_id: Optional[UUID] = Query(None),
    q: Optional[str] = Query(None, description="Optional resource label search"),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    access = UsageAccessPolicy.resolve(organization_id, start, end, tz)
    filter_start = access.filter_start
    filter_end = access.filter_end
    enforced_floor = access.enforced_filter_floor

    cache_key = cache_key_for(
        access,
        workspace_id=workspace_id,
        product_section=product_section,
        model=model,
        resource_id=resource_id,
        usage_kind=usage_kind,
        call_import_id=call_import_id,
        evaluation_id=evaluation_id,
        dataset=dataset,
        tag_id=tag_id,
        q=q,
    )
    cached_response, cache_leader, cache_version = _prepare_usage_read(
        organization_id, "filters", cache_key, UsageFiltersResponse
    )
    if cached_response is not None:
        return cached_response

    try:
        scoped_resource_id = resource_id or evaluation_id

        workspace_base = _filtered_query(
            db,
            organization_id=organization_id,
            start=filter_start,
            end=filter_end,
            enforced_floor=enforced_floor,
            dataset=dataset,
            tag_id=tag_id,
        )
        section_base = _filtered_query(
            db,
            organization_id=organization_id,
            start=filter_start,
            end=filter_end,
            enforced_floor=enforced_floor,
            workspace_id=workspace_id,
            dataset=dataset,
            tag_id=tag_id,
        )
        kind_base = _filtered_query(
            db,
            organization_id=organization_id,
            start=filter_start,
            end=filter_end,
            enforced_floor=enforced_floor,
            workspace_id=workspace_id,
            product_section=product_section,
            resource_id=scoped_resource_id,
            call_import_id=call_import_id,
            evaluation_id=evaluation_id,
            dataset=dataset,
            tag_id=tag_id,
        )
        model_base = _filtered_query(
            db,
            organization_id=organization_id,
            start=filter_start,
            end=filter_end,
            enforced_floor=enforced_floor,
            workspace_id=workspace_id,
            product_section=product_section,
            resource_id=scoped_resource_id,
            usage_kind=usage_kind,
            call_import_id=call_import_id,
            evaluation_id=evaluation_id,
            dataset=dataset,
            tag_id=tag_id,
        )
        call_import_base = _filtered_query(
            db,
            organization_id=organization_id,
            start=filter_start,
            end=filter_end,
            enforced_floor=enforced_floor,
            workspace_id=workspace_id,
            product_section=product_section,
            dataset=dataset,
            tag_id=tag_id,
        )
        resource_base = _filtered_query(
            db,
            organization_id=organization_id,
            start=filter_start,
            end=filter_end,
            enforced_floor=enforced_floor,
            workspace_id=workspace_id,
            product_section=product_section,
            model=model,
            usage_kind=usage_kind,
            call_import_id=call_import_id,
            dataset=dataset,
            tag_id=tag_id,
        )

        if _filters_share_facet_scan(
            workspace_id=workspace_id,
            product_section=product_section,
            model=model,
            resource_id=scoped_resource_id,
            usage_kind=usage_kind,
            call_import_id=call_import_id,
            evaluation_id=evaluation_id,
        ):
            workspace_ids, section_values, kind_values, model_values = _facet_sets(
                workspace_base
            )
            sections = sorted(section_values)
            models = sorted(model_values)
            kinds = sorted(kind_values)
        else:
            workspace_ids = {
                row[0]
                for row in workspace_base.with_entities(LLMUsageDaily.workspace_id)
                .distinct()
                .all()
                if row[0] is not None
            }
            sections = sorted(
                {
                    row[0]
                    for row in section_base.with_entities(LLMUsageDaily.product_section)
                    .distinct()
                    .all()
                    if row[0]
                }
            )
            models = sorted(
                {
                    row[0]
                    for row in model_base.with_entities(LLMUsageDaily.model).distinct().all()
                    if row[0]
                }
            )
            kinds = sorted(
                {
                    row[0]
                    for row in kind_base.with_entities(LLMUsageDaily.usage_kind).distinct().all()
                    if row[0]
                }
            )
        if (
            workspace_id is not None
            and workspace_id not in workspace_ids
        ):
            selected = (
                db.query(Workspace)
                .filter(
                    Workspace.id == workspace_id,
                    Workspace.organization_id == organization_id,
                )
                .first()
            )
            if selected is not None:
                workspace_ids.add(selected.id)
        workspaces = [
            {"id": str(w.id), "name": w.name}
            for w in db.query(Workspace)
            .filter(Workspace.id.in_(workspace_ids) if workspace_ids else False)
            .order_by(Workspace.name)
            .all()
        ]

        call_import_labels = _call_import_filter_labels(
            db,
            organization_id,
            call_import_base,
            workspace_id=workspace_id,
            dataset=dataset,
            tag_id=tag_id,
            call_import_id=call_import_id,
        )
        call_imports = [
            {"id": cid, "label": label}
            for cid, label in sorted(call_import_labels.items(), key=lambda x: x[1].lower())
        ]

        pinned_resources = [
            str(value)
            for value in (resource_id, evaluation_id)
            if value is not None
        ]
        resource_labels, resource_meta, evaluation_labels = _resource_filter_bundle(
            db,
            organization_id,
            resource_base,
            extra_resource_ids=pinned_resources,
        )
        needle = (q or "").strip().lower()
        evaluations = []
        for rid, label in sorted(evaluation_labels.items(), key=lambda x: x[1].lower()):
            if needle and needle not in label.lower():
                continue
            evaluations.append({"id": rid, "label": label})
        resources = []
        for rid, label in sorted(resource_labels.items(), key=lambda x: x[1].lower()):
            if needle and needle not in label.lower():
                continue
            info = resource_meta.get(rid, {})
            rtype = info.get("type")
            if rtype == "call_import_evaluation":
                continue
            resources.append(
                {
                    "id": rid,
                    "label": label,
                    "type": rtype,
                    "product_section": info.get("product_section"),
                }
            )

        dataset_query = db.query(CallImport.dataset).filter(
            CallImport.organization_id == organization_id,
            CallImport.dataset.isnot(None),
            CallImport.dataset != "",
        )
        if workspace_id is not None:
            dataset_query = dataset_query.filter(CallImport.workspace_id == workspace_id)
        if dataset or tag_id is not None:
            dataset_query = dataset_query.filter(
                CallImport.id.in_(
                    _scoped_call_import_id_select(
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        dataset=dataset,
                        tag_id=tag_id,
                    )
                )
            )
        datasets = sorted({row[0] for row in dataset_query.distinct().all() if row[0]})

        tags = [
            {"id": str(tag.id), "label": tag.name}
            for tag in (
                db.query(CallImportTag)
                .filter(CallImportTag.organization_id == organization_id)
                .order_by(CallImportTag.name)
                .all()
            )
        ]

        response = UsageFiltersResponse(
            workspaces=workspaces,
            product_sections=[
                {"id": s, "label": SECTION_LABELS.get(s, s)} for s in sections
            ],
            call_imports=call_imports,
            evaluations=evaluations,
            models=models,
            resources=resources,
            usage_kinds=[{"id": k, "label": usage_kind_label(k)} for k in kinds],
            datasets=datasets,
            tags=tags,
        )
        set_cached_response(
            organization_id,
            "filters",
            cache_key,
            response.model_dump(mode="json"),
            historical=_usage_range_is_historical(access),
            version=cache_version,
        )
        return response
    finally:
        if cache_leader:
            release_read_lock(organization_id, "filters", cache_key)

