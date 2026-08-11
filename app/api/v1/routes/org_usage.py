"""Org-scoped LLM Usage API (tokens + call counts)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_organization_id
from app.models.database import CallImportEvaluation, LLMUsageDaily, Workspace
from app.services.usage.llm_usage import flush_usage_to_catalog, merge_usage_totals

router = APIRouter(prefix="/organizations/usage", tags=["Usage"])

GroupBy = Literal["workspace", "product_section", "model", "resource"]

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


class UsageTotals(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0
    call_count: int = 0


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
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0
    call_count: int = 0


class UsageBreakdownResponse(BaseModel):
    start: date
    end: date
    group_by: GroupBy
    rows: List[UsageBreakdownRow]
    total_count: int
    last_updated_at: Optional[datetime] = None


class UsageFiltersResponse(BaseModel):
    workspaces: List[dict] = Field(default_factory=list)
    product_sections: List[dict] = Field(default_factory=list)
    models: List[str] = Field(default_factory=list)
    resources: List[dict] = Field(default_factory=list)


def _default_range() -> tuple[date, date]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=29)
    return start, end


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
):
    query = query.filter(
        LLMUsageDaily.organization_id == organization_id,
        LLMUsageDaily.usage_date >= start,
        LLMUsageDaily.usage_date <= end,
    )
    if workspace_id is not None:
        query = query.filter(LLMUsageDaily.workspace_id == workspace_id)
    if product_section:
        query = query.filter(LLMUsageDaily.product_section == product_section)
    if model:
        query = query.filter(LLMUsageDaily.model == model)
    if resource_id is not None:
        query = query.filter(LLMUsageDaily.resource_id == resource_id)
    return query


def _last_updated(db: Session, organization_id: UUID) -> Optional[datetime]:
    return (
        db.query(func.max(LLMUsageDaily.updated_at))
        .filter(LLMUsageDaily.organization_id == organization_id)
        .scalar()
    )


@router.get("/summary", response_model=UsageSummaryResponse)
def get_usage_summary(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    workspace_id: Optional[UUID] = Query(None),
    product_section: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    resource_id: Optional[UUID] = Query(None),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    if start is None or end is None:
        start, end = _default_range()
    if end < start:
        raise HTTPException(status_code=400, detail="end must be >= start")

    flush_usage_to_catalog(db, organization_id)

    query = _apply_filters(
        db.query(LLMUsageDaily),
        organization_id=organization_id,
        start=start,
        end=end,
        workspace_id=workspace_id,
        product_section=product_section,
        model=model,
        resource_id=resource_id,
    )
    rows = query.all()
    totals = merge_usage_totals(rows)
    return UsageSummaryResponse(
        start=start,
        end=end,
        totals=UsageTotals(**totals),
        last_updated_at=_last_updated(db, organization_id),
    )


@router.get("/breakdown", response_model=UsageBreakdownResponse)
def get_usage_breakdown(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    group_by: GroupBy = Query("workspace"),
    workspace_id: Optional[UUID] = Query(None),
    product_section: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    resource_id: Optional[UUID] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    if start is None or end is None:
        start, end = _default_range()
    if end < start:
        raise HTTPException(status_code=400, detail="end must be >= start")

    flush_usage_to_catalog(db, organization_id)

    dim = {
        "workspace": LLMUsageDaily.workspace_id,
        "product_section": LLMUsageDaily.product_section,
        "model": LLMUsageDaily.model,
        "resource": LLMUsageDaily.resource_id,
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
        func.coalesce(func.sum(LLMUsageDaily.call_count), 0).label("call_count"),
    ]

    select_cols = [dim]
    group_cols = [dim]
    if group_by == "resource":
        select_cols.append(LLMUsageDaily.resource_type)
        group_cols.append(LLMUsageDaily.resource_type)

    query = _apply_filters(
        db.query(*select_cols, *aggregates),
        organization_id=organization_id,
        start=start,
        end=end,
        workspace_id=workspace_id,
        product_section=product_section,
        model=model,
        resource_id=resource_id,
    ).group_by(*group_cols)

    total_count = query.count()
    results = (
        query.order_by(func.sum(LLMUsageDaily.call_count).desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    workspace_names = {
        w.id: w.name
        for w in db.query(Workspace)
        .filter(Workspace.organization_id == organization_id)
        .all()
    }
    resource_labels: dict = {}
    if group_by == "resource":
        resource_ids = [r[0] for r in results if r[0] is not None]
        if resource_ids:
            evals = (
                db.query(CallImportEvaluation)
                .filter(
                    CallImportEvaluation.organization_id == organization_id,
                    CallImportEvaluation.id.in_(resource_ids),
                )
                .all()
            )
            for evaluation in evals:
                label = (evaluation.name or "").strip() or str(evaluation.id)[:8]
                resource_labels[evaluation.id] = label

    rows: List[UsageBreakdownRow] = []
    for result in results:
        if group_by == "workspace":
            ws_id = result[0]
            metrics = result[1:]
            rows.append(
                UsageBreakdownRow(
                    workspace_id=ws_id,
                    workspace_name=workspace_names.get(ws_id) if ws_id else "Unknown",
                    prompt_tokens=int(metrics[0]),
                    completion_tokens=int(metrics[1]),
                    total_tokens=int(metrics[0]) + int(metrics[1]),
                    cache_read_tokens=int(metrics[2]),
                    cache_creation_tokens=int(metrics[3]),
                    reasoning_tokens=int(metrics[4]),
                    call_count=int(metrics[5]),
                )
            )
        elif group_by == "product_section":
            section = result[0]
            metrics = result[1:]
            rows.append(
                UsageBreakdownRow(
                    product_section=section,
                    product_section_label=SECTION_LABELS.get(section or "", section),
                    prompt_tokens=int(metrics[0]),
                    completion_tokens=int(metrics[1]),
                    total_tokens=int(metrics[0]) + int(metrics[1]),
                    cache_read_tokens=int(metrics[2]),
                    cache_creation_tokens=int(metrics[3]),
                    reasoning_tokens=int(metrics[4]),
                    call_count=int(metrics[5]),
                )
            )
        elif group_by == "model":
            model_name = result[0]
            metrics = result[1:]
            rows.append(
                UsageBreakdownRow(
                    model=model_name,
                    prompt_tokens=int(metrics[0]),
                    completion_tokens=int(metrics[1]),
                    total_tokens=int(metrics[0]) + int(metrics[1]),
                    cache_read_tokens=int(metrics[2]),
                    cache_creation_tokens=int(metrics[3]),
                    reasoning_tokens=int(metrics[4]),
                    call_count=int(metrics[5]),
                )
            )
        else:
            res_id, res_type = result[0], result[1]
            metrics = result[2:]
            rows.append(
                UsageBreakdownRow(
                    resource_id=res_id,
                    resource_type=res_type,
                    resource_label=resource_labels.get(res_id)
                    if res_id
                    else "Unscoped",
                    prompt_tokens=int(metrics[0]),
                    completion_tokens=int(metrics[1]),
                    total_tokens=int(metrics[0]) + int(metrics[1]),
                    cache_read_tokens=int(metrics[2]),
                    cache_creation_tokens=int(metrics[3]),
                    reasoning_tokens=int(metrics[4]),
                    call_count=int(metrics[5]),
                )
            )

    return UsageBreakdownResponse(
        start=start,
        end=end,
        group_by=group_by,
        rows=rows,
        total_count=total_count,
        last_updated_at=_last_updated(db, organization_id),
    )


@router.get("/filters", response_model=UsageFiltersResponse)
def get_usage_filters(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    if start is None or end is None:
        start, end = _default_range()

    flush_usage_to_catalog(db, organization_id)

    base = db.query(LLMUsageDaily).filter(
        LLMUsageDaily.organization_id == organization_id,
        LLMUsageDaily.usage_date >= start,
        LLMUsageDaily.usage_date <= end,
    )

    workspace_ids = {
        row[0]
        for row in base.with_entities(LLMUsageDaily.workspace_id).distinct().all()
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
            for row in base.with_entities(LLMUsageDaily.product_section).distinct().all()
            if row[0]
        }
    )
    models = sorted(
        {
            row[0]
            for row in base.with_entities(LLMUsageDaily.model).distinct().all()
            if row[0]
        }
    )

    resource_rows = (
        base.with_entities(LLMUsageDaily.resource_id, LLMUsageDaily.resource_type)
        .filter(LLMUsageDaily.resource_id.isnot(None))
        .distinct()
        .limit(100)
        .all()
    )
    resource_ids = [r[0] for r in resource_rows]
    eval_names = {}
    if resource_ids:
        for evaluation in (
            db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id.in_(resource_ids))
            .all()
        ):
            eval_names[evaluation.id] = (evaluation.name or "").strip() or str(
                evaluation.id
            )[:8]

    resources = [
        {
            "id": str(rid),
            "type": rtype,
            "label": eval_names.get(rid, str(rid)[:8]),
        }
        for rid, rtype in resource_rows
        if rid is not None
    ]

    return UsageFiltersResponse(
        workspaces=workspaces,
        product_sections=[
            {"id": s, "label": SECTION_LABELS.get(s, s)} for s in sections
        ],
        models=models,
        resources=resources,
    )
