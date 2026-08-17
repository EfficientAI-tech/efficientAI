"""Org-scoped usage pricing overrides and recompute API."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth.rbac import require_admin
from app.database import get_db
from app.dependencies import get_organization_id, require_enterprise_entitlement
from app.services.usage.pricing_jobs import (
    create_recompute_job,
    enqueue_recompute_job,
    get_recompute_job,
    job_to_dict,
)
from app.services.usage.pricing_overrides import (
    delete_override,
    get_effective_rate,
    list_effective_pricing,
    list_overrides,
    upsert_override,
)

from app.services.usage.access import UsageAccessPolicy

router = APIRouter(
    prefix="/organizations/usage/pricing",
    tags=["Usage"],
    dependencies=[Depends(require_admin), Depends(require_enterprise_entitlement())],
)


class PricingRatesUsd(BaseModel):
    input_per_1m: Optional[float] = None
    output_per_1m: Optional[float] = None
    cache_read_per_1m: Optional[float] = None
    cache_write_per_1m: Optional[float] = None
    reasoning_per_1m: Optional[float] = None
    audio_per_minute: Optional[float] = None
    tts_per_1m_characters: Optional[float] = None


class PricingOverrideResponse(BaseModel):
    id: str
    organization_id: str
    model: str
    usage_kind: str
    effective_from: date
    effective_to: Optional[date] = None
    rates: PricingRatesUsd
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    recompute_enqueued: Optional[bool] = None
    recompute_job_id: Optional[str] = None


class PricingOverrideUpsertRequest(BaseModel):
    usage_kind: str = "llm"
    effective_from: date
    effective_to: Optional[date] = None
    rates: PricingRatesUsd
    recompute: bool = False


class EffectivePricingResponse(BaseModel):
    model: str
    usage_kind: str
    as_of: date
    catalog_rates: Optional[PricingRatesUsd] = None
    catalog_rate_id: Optional[str] = None
    override: Optional[PricingOverrideResponse] = None
    effective_rates: Optional[PricingRatesUsd] = None
    effective_source: Optional[str] = None
    effective_rate_id: Optional[str] = None
    has_override: bool = False


class PricingOverrideDeleteResponse(BaseModel):
    deleted: bool
    model: str
    usage_kind: str
    recompute_enqueued: bool = False
    recompute_job_id: Optional[str] = None


class UsageRecomputeRequest(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    model: Optional[str] = None
    usage_kind: Optional[str] = None


class UsageRecomputeJobResponse(BaseModel):
    id: UUID
    organization_id: UUID
    status: str
    model: Optional[str] = None
    usage_kind: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    updated_rows: int = 0
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AvailableModelsResponse(BaseModel):
    models: List[str]


@router.get("/available-models", response_model=AvailableModelsResponse)
def list_pricing_available_models(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    from app.services.usage.enabled_models import org_pricing_eligible_models

    return AvailableModelsResponse(
        models=org_pricing_eligible_models(db, organization_id),
    )


@router.get("", response_model=List[EffectivePricingResponse])
def list_effective_usage_pricing(
    usage_kind: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    as_of: Optional[date] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    day = as_of or date.today()
    rows = list_effective_pricing(
        db,
        organization_id=organization_id,
        usage_kind=usage_kind,
        model=model,
        as_of=day,
        limit=limit,
    )
    return rows


@router.get("/overrides", response_model=List[PricingOverrideResponse])
def list_usage_pricing_overrides(
    model: Optional[str] = Query(None),
    usage_kind: Optional[str] = Query(None),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    return list_overrides(
        db,
        organization_id=organization_id,
        model=model,
        usage_kind=usage_kind,
    )


@router.get("/overrides/{model}", response_model=EffectivePricingResponse)
def get_usage_pricing_override_effective(
    model: str,
    usage_kind: str = Query("llm"),
    as_of: Optional[date] = Query(None),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    return get_effective_rate(
        db,
        organization_id=organization_id,
        model=model,
        usage_kind=usage_kind,
        as_of=as_of or date.today(),
    )


@router.put("/overrides/{model}", response_model=PricingOverrideResponse)
def upsert_usage_pricing_override(
    model: str,
    body: PricingOverrideUpsertRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    return upsert_override(
        db,
        organization_id=organization_id,
        model=model,
        usage_kind=body.usage_kind,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        rates=body.rates.model_dump(exclude_unset=True),
        recompute=body.recompute,
    )


@router.delete("/overrides/{model}", response_model=PricingOverrideDeleteResponse)
def delete_usage_pricing_override(
    model: str,
    usage_kind: str = Query("llm"),
    effective_from: Optional[date] = Query(None),
    recompute: bool = Query(False),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    return delete_override(
        db,
        organization_id=organization_id,
        model=model,
        usage_kind=usage_kind,
        effective_from=effective_from,
        recompute=recompute,
    )


@router.post(
    "/recompute",
    response_model=UsageRecomputeJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_usage_cost_recompute(
    body: UsageRecomputeRequest,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    if (
        body.start_date is not None
        and body.end_date is not None
        and body.end_date < body.start_date
    ):
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")

    clamped_start = body.start_date
    clamped_end = body.end_date
    if body.start_date is not None or body.end_date is not None:
        access = UsageAccessPolicy.resolve(
            organization_id,
            body.start_date,
            body.end_date,
            None,
        )
        clamped_start = access.display_start if body.start_date is not None else None
        clamped_end = access.display_end if body.end_date is not None else None

    job = create_recompute_job(
        db,
        organization_id=organization_id,
        model=body.model,
        usage_kind=body.usage_kind,
        start_date=clamped_start,
        end_date=clamped_end,
    )
    enqueue_recompute_job(db, job)
    db.refresh(job)
    return UsageRecomputeJobResponse(**job_to_dict(job))


@router.get("/recompute/{job_id}", response_model=UsageRecomputeJobResponse)
def get_usage_cost_recompute_job(
    job_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    job = get_recompute_job(db, organization_id=organization_id, job_id=job_id)
    return UsageRecomputeJobResponse(**job_to_dict(job))
