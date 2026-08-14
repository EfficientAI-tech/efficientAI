"""Org-scoped LLM Usage API (tokens + call counts)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from app.services.usage.dates import usage_date_filter_bounds, usage_local_today
from typing import List, Literal, Optional
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
    CallImportEvaluationRow,
    CallImportRow,
    CallImportTag,
    CallImportTagAssignment,
    Agent,
    LLMUsageDaily,
    Workspace,
)
from app.services.usage.llm_usage import flush_usage_to_catalog
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

_LABEL_ROW_LIMIT = 5000


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


def _label_row_order():
    return (
        _usage_row_weight().desc(),
        LLMUsageDaily.call_count.desc(),
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


class UsageSummaryResponse(BaseModel):
    start: date
    end: date
    totals: UsageTotals
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


def _call_import_group_expr():
    """Resolve call import id from context, resource row, evaluation, or import row."""
    eval_call_import = (
        select(CallImportEvaluation.call_import_id)
        .where(
            CallImportEvaluation.id == cast(_evaluation_id_expr(), PG_UUID)
        )
        .correlate(LLMUsageDaily)
        .scalar_subquery()
    )
    row_call_import = (
        select(CallImportRow.call_import_id)
        .where(
            CallImportRow.id
            == cast(LLMUsageDaily.context["call_import_row_id"].astext, PG_UUID)
        )
        .correlate(LLMUsageDaily)
        .scalar_subquery()
    )
    eval_row_call_import = (
        select(CallImportEvaluation.call_import_id)
        .select_from(CallImportEvaluationRow)
        .join(
            CallImportEvaluation,
            CallImportEvaluation.id == CallImportEvaluationRow.evaluation_id,
        )
        .where(
            CallImportEvaluationRow.id
            == cast(LLMUsageDaily.context["evaluation_row_id"].astext, PG_UUID)
        )
        .correlate(LLMUsageDaily)
        .scalar_subquery()
    )
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
            cast(eval_call_import, String),
            cast(row_call_import, String),
            cast(eval_row_call_import, String),
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
    eid = str(evaluation_id)
    row_ids = [
        str(row[0])
        for row in db.query(CallImportEvaluationRow.id)
        .filter(
            CallImportEvaluationRow.evaluation_id == evaluation_id,
        )
        .all()
    ]
    clauses = [
        LLMUsageDaily.context["evaluation_id"].astext == eid,
        and_(
            LLMUsageDaily.context["resource_id"].astext == eid,
            LLMUsageDaily.context["resource_type"].astext == "call_import_evaluation",
        ),
    ]
    if row_ids:
        clauses.append(LLMUsageDaily.context["evaluation_row_id"].astext.in_(row_ids))
    return or_(*clauses)


def _call_import_scope_filter(
    call_import_id: UUID,
    organization_id: UUID,
    db: Session,
):
    """Match usage tied to a call import (direct context, resource row, or eval runs)."""
    cid = str(call_import_id)
    eval_ids = [
        str(row[0])
        for row in db.query(CallImportEvaluation.id)
        .filter(
            CallImportEvaluation.organization_id == organization_id,
            CallImportEvaluation.call_import_id == call_import_id,
        )
        .all()
    ]
    clauses = [
        LLMUsageDaily.context["call_import_id"].astext == cid,
        and_(
            LLMUsageDaily.context["resource_id"].astext == cid,
            LLMUsageDaily.context["resource_type"].astext == "call_import",
        ),
    ]
    if eval_ids:
        clauses.append(LLMUsageDaily.context["evaluation_id"].astext.in_(eval_ids))
        clauses.append(
            and_(
                LLMUsageDaily.context["resource_id"].astext.in_(eval_ids),
                LLMUsageDaily.context["resource_type"].astext == "call_import_evaluation",
            )
        )
    return or_(*clauses)


def _call_import_ids_for_filters(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID] = None,
    dataset: Optional[str] = None,
    tag_id: Optional[UUID] = None,
) -> List[UUID]:
    query = db.query(CallImport.id).filter(
        CallImport.organization_id == organization_id,
    )
    if workspace_id is not None:
        query = query.filter(CallImport.workspace_id == workspace_id)
    if dataset:
        query = query.filter(CallImport.dataset == dataset)
    if tag_id is not None:
        query = query.filter(
            CallImport.id.in_(
                db.query(CallImportTagAssignment.call_import_id).filter(
                    CallImportTagAssignment.tag_id == tag_id,
                )
            )
        )
    return [row[0] for row in query.all()]


def _call_import_ids_scope_filter(
    allowed_import_ids: List[UUID],
):
    if not allowed_import_ids:
        return LLMUsageDaily.id.is_(None)
    allowed = [str(uid) for uid in allowed_import_ids]
    return cast(_call_import_group_expr(), String).in_(allowed)


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
    legacy_call_import = and_(
        LLMUsageDaily.workspace_id.is_(None),
        _call_import_group_expr().in_(ws_call_import_ids),
    )
    return or_(LLMUsageDaily.workspace_id == workspace_id, legacy_call_import)


def _apply_filters(
    query,
    *,
    organization_id: UUID,
    start: date,
    end: date,
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
    query = query.filter(
        LLMUsageDaily.organization_id == organization_id,
        LLMUsageDaily.usage_date >= start,
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
        allowed = _call_import_ids_for_filters(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            dataset=dataset,
            tag_id=tag_id,
        )
        query = query.filter(_call_import_ids_scope_filter(allowed))
    return query


def _filtered_query(
    db: Session,
    *,
    organization_id: UUID,
    start: date,
    end: date,
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


def _resource_label_map(
    db: Session,
    organization_id: UUID,
    query,
) -> dict[str, str]:
    """Build resource_id -> hierarchical label from usage rows in query."""
    rows = (
        query.with_entities(
            _resource_id_expr(),
            _resource_type_expr(),
            LLMUsageDaily.context,
        )
        .filter(
            or_(
                LLMUsageDaily.context["resource_id"].astext.isnot(None),
                LLMUsageDaily.context["agent_id"].astext.isnot(None),
            )
        )
        .order_by(*_label_row_order())
        .limit(_LABEL_ROW_LIMIT)
        .all()
    )
    grouped: dict[str, tuple[Optional[str], list]] = {}
    for raw_id, rtype, ctx in rows:
        if not raw_id:
            continue
        key = str(raw_id)
        if key not in grouped:
            grouped[key] = (rtype, [])
        grouped[key][1].append(ctx)

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
    resolver.preload(contexts_for_preload)
    return labels_for_resource_buckets(buckets, resolver)


def _resource_filter_meta_map(
    db: Session,
    organization_id: UUID,
    query,
) -> dict[str, dict[str, Optional[str]]]:
    """Map resource id -> {type, product_section} for filter dropdowns."""
    rows = (
        query.with_entities(
            _resource_id_expr(),
            _resource_type_expr(),
            LLMUsageDaily.product_section,
        )
        .filter(
            or_(
                LLMUsageDaily.context["resource_id"].astext.isnot(None),
                LLMUsageDaily.context["agent_id"].astext.isnot(None),
            )
        )
        .distinct()
        .limit(_LABEL_ROW_LIMIT)
        .all()
    )
    meta: dict[str, dict[str, Optional[str]]] = {}
    for raw_id, rtype, section in rows:
        if not raw_id:
            continue
        key = str(raw_id)
        entry = meta.setdefault(key, {"type": None, "product_section": None})
        if rtype:
            entry["type"] = str(rtype)
        if section:
            entry["product_section"] = str(section)
        if not entry["type"] and section == "agents":
            entry["type"] = "agent"
    return meta


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


def _collect_call_import_ids_from_usage_rows(
    db: Session,
    organization_id: UUID,
    rows: list,
) -> set[UUID]:
    """Extract call import ids referenced in usage row context tuples."""
    import_ids: set[UUID] = set()
    eval_ids: set[UUID] = set()
    row_ids: set[UUID] = set()
    eval_row_ids: set[UUID] = set()

    for row in rows:
        cid_raw = row[0] if len(row) > 0 else None
        res_raw = row[1] if len(row) > 1 else None
        rtype = row[2] if len(row) > 2 else None
        eval_raw = row[3] if len(row) > 3 else None
        row_id_raw = row[4] if len(row) > 4 else None
        eval_row_raw = row[5] if len(row) > 5 else None

        if cid_raw:
            uid = parse_uuid(cid_raw)
            if uid:
                import_ids.add(uid)
        if res_raw and rtype == "call_import":
            uid = parse_uuid(res_raw)
            if uid:
                import_ids.add(uid)
        if eval_raw:
            uid = parse_uuid(eval_raw)
            if uid:
                eval_ids.add(uid)
        if res_raw and rtype == "call_import_evaluation":
            uid = parse_uuid(res_raw)
            if uid:
                eval_ids.add(uid)
        if row_id_raw:
            uid = parse_uuid(row_id_raw)
            if uid:
                row_ids.add(uid)
        if eval_row_raw:
            uid = parse_uuid(eval_row_raw)
            if uid:
                eval_row_ids.add(uid)

    if eval_ids:
        for ev in (
            db.query(CallImportEvaluation)
            .filter(
                CallImportEvaluation.organization_id == organization_id,
                CallImportEvaluation.id.in_(eval_ids),
            )
            .all()
        ):
            import_ids.add(ev.call_import_id)

    if row_ids:
        for cid in (
            db.query(CallImportRow.call_import_id)
            .filter(CallImportRow.id.in_(row_ids))
            .distinct()
            .all()
        ):
            import_ids.add(cid[0])

    if eval_row_ids:
        for cid in (
            db.query(CallImportEvaluation.call_import_id)
            .join(
                CallImportEvaluationRow,
                CallImportEvaluationRow.evaluation_id == CallImportEvaluation.id,
            )
            .filter(CallImportEvaluationRow.id.in_(eval_row_ids))
            .distinct()
            .all()
        ):
            import_ids.add(cid[0])

    return import_ids


def _call_import_label_map(
    db: Session,
    organization_id: UUID,
    query,
) -> dict[str, str]:
    rows = (
        query.with_entities(
            LLMUsageDaily.context["call_import_id"].astext,
            LLMUsageDaily.context["resource_id"].astext,
            LLMUsageDaily.context["resource_type"].astext,
            LLMUsageDaily.context["evaluation_id"].astext,
            LLMUsageDaily.context["call_import_row_id"].astext,
            LLMUsageDaily.context["evaluation_row_id"].astext,
        )
        .order_by(*_label_row_order())
        .limit(_LABEL_ROW_LIMIT)
        .all()
    )
    import_ids = _collect_call_import_ids_from_usage_rows(
        db, organization_id, rows
    )

    if not import_ids:
        return {}
    resolver = UsageNameResolver(db, organization_id)
    resolver.preload(
        [{"call_import_id": str(uid)} for uid in import_ids]
    )
    return labels_for_call_import_ids(list(import_ids), resolver)


def _call_import_filter_labels(
    db: Session,
    organization_id: UUID,
    query,
    workspace_id: Optional[UUID] = None,
    dataset: Optional[str] = None,
    tag_id: Optional[UUID] = None,
) -> dict[str, str]:
    """Call imports for filters: usage in range plus workspace imports when scoped."""
    import_ids = _collect_call_import_ids_from_usage_rows(
        db,
        organization_id,
        query.with_entities(
            LLMUsageDaily.context["call_import_id"].astext,
            LLMUsageDaily.context["resource_id"].astext,
            LLMUsageDaily.context["resource_type"].astext,
            LLMUsageDaily.context["evaluation_id"].astext,
            LLMUsageDaily.context["call_import_row_id"].astext,
            LLMUsageDaily.context["evaluation_row_id"].astext,
        ).order_by(*_label_row_order()).limit(_LABEL_ROW_LIMIT).all(),
    )

    if workspace_id is not None:
        scoped_ids = _call_import_ids_for_filters(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            dataset=dataset,
            tag_id=tag_id,
        )
        import_ids.update(scoped_ids)

    if not import_ids:
        return {}
    resolver = UsageNameResolver(db, organization_id)
    resolver.preload([{"call_import_id": str(uid)} for uid in import_ids])
    return labels_for_call_import_ids(list(import_ids), resolver)


def _evaluation_label_map(
    db: Session,
    organization_id: UUID,
    query,
) -> dict[str, str]:
    """Evaluation id -> short label (name + id suffix) for filter dropdowns."""
    rows = (
        query.with_entities(
            LLMUsageDaily.context["evaluation_id"].astext,
            LLMUsageDaily.context["resource_id"].astext,
            LLMUsageDaily.context["resource_type"].astext,
            LLMUsageDaily.context,
        )
        .filter(
            or_(
                LLMUsageDaily.context["evaluation_id"].astext.isnot(None),
                LLMUsageDaily.context["resource_type"].astext == "call_import_evaluation",
            )
        )
        .order_by(*_label_row_order())
        .limit(_LABEL_ROW_LIMIT)
        .all()
    )
    grouped: dict[str, tuple[Optional[str], list]] = {}
    for eval_raw, res_raw, rtype, ctx in rows:
        key_raw = eval_raw
        if not key_raw and rtype == "call_import_evaluation" and res_raw:
            key_raw = res_raw
        if not key_raw:
            continue
        key = str(key_raw)
        if key not in grouped:
            grouped[key] = (rtype, [])
        grouped[key][1].append(ctx)

    buckets = [(rid, rtype, contexts) for rid, (rtype, contexts) in grouped.items()]
    resolver = UsageNameResolver(db, organization_id)
    contexts_for_preload = []
    for _, rtype, contexts in buckets:
        for ctx in contexts:
            merged = dict(ctx or {})
            if rtype and "resource_type" not in merged:
                merged["resource_type"] = rtype
            contexts_for_preload.append(merged)
    resolver.preload(contexts_for_preload)

    labels: dict[str, str] = {}
    for raw_id, rtype, contexts in buckets:
        ctx = max([dict(c or {}) for c in contexts], key=len, default={})
        if rtype and "resource_type" not in ctx:
            ctx["resource_type"] = rtype
        eval_key = ctx.get("evaluation_id") or raw_id
        labels[str(raw_id)] = resolver.evaluation_name(str(eval_key))
    return labels


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
        db.query(func.max(LLMUsageDaily.updated_at))
        .filter(LLMUsageDaily.organization_id == organization_id)
        .scalar()
    )


def _summary_aggregate_query(
    db: Session,
    *,
    organization_id: UUID,
    start: date,
    end: date,
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
    display_start, display_end, filter_start, filter_end = _parse_usage_range(
        start, end, tz
    )
    if display_end < display_start:
        raise HTTPException(status_code=400, detail="end must be >= start")

    flush_usage_to_catalog(db, organization_id)

    row = _summary_aggregate_query(
        db,
        organization_id=organization_id,
        start=filter_start,
        end=filter_end,
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
    return UsageSummaryResponse(
        start=display_start,
        end=display_end,
        totals=UsageTotals(**totals),
        last_updated_at=_last_updated(db, organization_id),
    )


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
    display_start, display_end, filter_start, filter_end = _parse_usage_range(
        start, end, tz
    )
    if display_end < display_start:
        raise HTTPException(status_code=400, detail="end must be >= start")

    flush_usage_to_catalog(db, organization_id)

    dim = {
        "workspace": LLMUsageDaily.workspace_id,
        "product_section": LLMUsageDaily.product_section,
        "model": LLMUsageDaily.model,
        "resource": cast(_resource_id_expr(), String),
        "usage_kind": LLMUsageDaily.usage_kind,
        "call_import": _call_import_group_expr(),
    }[group_by]

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

    select_cols = [dim]
    group_cols = [dim]
    if group_by == "resource":
        select_cols.append(cast(_resource_type_expr(), String))
        group_cols.append(cast(_resource_type_expr(), String))
        select_cols.append(LLMUsageDaily.product_section)
        group_cols.append(LLMUsageDaily.product_section)

    query = _apply_filters(
        db.query(*select_cols, *aggregates),
        organization_id=organization_id,
        start=filter_start,
        end=filter_end,
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
        query.order_by(func.sum(LLMUsageDaily.call_count).desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

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
        label_query = _filtered_query(
            db,
            organization_id=organization_id,
            start=filter_start,
            end=filter_end,
            workspace_id=workspace_id,
            product_section=product_section,
            model=model,
            resource_id=resource_id,
            usage_kind=usage_kind,
            call_import_id=call_import_id,
            evaluation_id=evaluation_id,
            evaluation_row_id=evaluation_row_id,
        )
        resource_labels = _resource_label_map(db, organization_id, label_query)
    elif group_by == "call_import":
        label_query = _filtered_query(
            db,
            organization_id=organization_id,
            start=filter_start,
            end=filter_end,
            workspace_id=workspace_id,
            product_section=product_section,
            model=model,
            resource_id=resource_id,
            usage_kind=usage_kind,
            call_import_id=call_import_id,
            evaluation_id=evaluation_id,
            evaluation_row_id=evaluation_row_id,
        )
        call_import_labels = _call_import_label_map(db, organization_id, label_query)

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

    return UsageBreakdownResponse(
        start=display_start,
        end=display_end,
        group_by=group_by,
        rows=rows,
        total_count=len(rows),
        truncated_at_limit=len(rows) >= limit,
        last_updated_at=_last_updated(db, organization_id),
    )


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
    _, _, filter_start, filter_end = _parse_usage_range(start, end, tz)

    flush_usage_to_catalog(db, organization_id)

    scoped_resource_id = resource_id or evaluation_id

    workspace_base = _filtered_query(
        db,
        organization_id=organization_id,
        start=filter_start,
        end=filter_end,
        dataset=dataset,
        tag_id=tag_id,
    )
    section_base = _filtered_query(
        db,
        organization_id=organization_id,
        start=filter_start,
        end=filter_end,
        workspace_id=workspace_id,
        dataset=dataset,
        tag_id=tag_id,
    )
    kind_base = _filtered_query(
        db,
        organization_id=organization_id,
        start=filter_start,
        end=filter_end,
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
        workspace_id=workspace_id,
        product_section=product_section,
        model=model,
        usage_kind=usage_kind,
        call_import_id=call_import_id,
        dataset=dataset,
        tag_id=tag_id,
    )

    workspace_ids = {
        row[0]
        for row in workspace_base.with_entities(LLMUsageDaily.workspace_id).distinct().all()
        if row[0] is not None
    }
    workspaces = [
        {"id": str(w.id), "name": w.name}
        for w in db.query(Workspace)
        .filter(Workspace.id.in_(workspace_ids) if workspace_ids else False)
        .order_by(Workspace.name)
        .all()
    ]

    sections = sorted(
        {
            row[0]
            for row in section_base.with_entities(LLMUsageDaily.product_section).distinct().all()
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

    call_import_labels = _call_import_filter_labels(
        db,
        organization_id,
        call_import_base,
        workspace_id=workspace_id,
        dataset=dataset,
        tag_id=tag_id,
    )
    call_imports = [
        {"id": cid, "label": label}
        for cid, label in sorted(call_import_labels.items(), key=lambda x: x[1].lower())
    ]

    evaluation_labels = _evaluation_label_map(db, organization_id, resource_base)
    needle = (q or "").strip().lower()
    evaluations = []
    for rid, label in sorted(evaluation_labels.items(), key=lambda x: x[1].lower()):
        if needle and needle not in label.lower():
            continue
        evaluations.append({"id": rid, "label": label})

    resource_labels = _resource_label_map(db, organization_id, resource_base)
    resource_meta = _resource_filter_meta_map(db, organization_id, resource_base)
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
        scoped_import_ids = _call_import_ids_for_filters(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            dataset=dataset,
            tag_id=tag_id,
        )
        if scoped_import_ids:
            dataset_query = dataset_query.filter(CallImport.id.in_(scoped_import_ids))
        else:
            dataset_query = dataset_query.filter(CallImport.id.is_(None))
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

    return UsageFiltersResponse(
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

