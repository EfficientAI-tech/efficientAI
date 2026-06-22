"""Dashboard summary routes."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_api_key, get_organization_id, get_workspace_id
from app.models.database import (
    Agent,
    CallImport,
    CallImportEvaluation,
    Evaluation,
    EvaluationStatus,
    Integration,
    Metric,
    MetricCategory,
    Persona,
    Scenario,
    VoiceBundle,
)
from app.models.schemas import EvaluationResponse

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

REMOVED_DEFAULT_METRICS = {"Clarity and Empathy", "Problem Resolution"}


class EvaluationCounts(BaseModel):
    total: int
    completed: int
    pending: int
    failed: int


class ResourceCounts(BaseModel):
    agents: int
    personas: int
    scenarios: int
    integrations: int
    voice_bundles: int


class SetupProgress(BaseModel):
    has_integration: bool
    has_voice_bundle: bool
    has_agent: bool
    has_evaluation: bool


class MetricCounts(BaseModel):
    total: int
    enabled: int


class CallImportCounts(BaseModel):
    total: int


class CallImportEvaluationCounts(BaseModel):
    total: int
    completed: int
    running: int
    failed: int


class DashboardSummaryResponse(BaseModel):
    evaluations: EvaluationCounts
    resources: ResourceCounts
    setup_progress: SetupProgress
    metrics: MetricCounts
    call_imports: CallImportCounts
    call_import_evaluations: CallImportEvaluationCounts
    recent_evaluations: List[EvaluationResponse]

    model_config = ConfigDict(from_attributes=True)


def _count_by_status(db: Session, organization_id: UUID, workspace_id: UUID) -> EvaluationCounts:
    rows = (
        db.query(Evaluation.status, func.count(Evaluation.id))
        .filter(
            Evaluation.organization_id == organization_id,
            Evaluation.workspace_id == workspace_id,
        )
        .group_by(Evaluation.status)
        .all()
    )
    counts = {status: count for status, count in rows}
    pending = (
        counts.get(EvaluationStatus.PENDING.value, 0)
        + counts.get(EvaluationStatus.PROCESSING.value, 0)
    )
    return EvaluationCounts(
        total=sum(counts.values()),
        completed=counts.get(EvaluationStatus.COMPLETED.value, 0),
        pending=pending,
        failed=counts.get(EvaluationStatus.FAILED.value, 0),
    )


def _metric_filters(organization_id: UUID, workspace_id: UUID):
    return (
        Metric.organization_id == organization_id,
        or_(Metric.workspace_id == workspace_id, Metric.workspace_id.is_(None)),
        ~Metric.name.in_(REMOVED_DEFAULT_METRICS),
        ~and_(
            Metric.is_default == True,
            Metric.metric_category == MetricCategory.USER_INSIGHT.value,
            Metric.metric_origin == "default",
        ),
    )


def _count_call_import_evaluations(
    db: Session, organization_id: UUID, workspace_id: UUID
) -> CallImportEvaluationCounts:
    rows = (
        db.query(CallImportEvaluation.status, func.count(CallImportEvaluation.id))
        .filter(
            CallImportEvaluation.organization_id == organization_id,
            CallImportEvaluation.workspace_id == workspace_id,
        )
        .group_by(CallImportEvaluation.status)
        .all()
    )
    counts = {status: count for status, count in rows}
    running = sum(
        counts.get(s, 0)
        for s in ("pending", "running", "queued", "processing")
    )
    return CallImportEvaluationCounts(
        total=sum(counts.values()),
        completed=counts.get("completed", 0),
        running=running,
        failed=counts.get("failed", 0),
    )


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Aggregated counts and recent activity for the home dashboard."""
    eval_counts = _count_by_status(db, organization_id, workspace_id)

    agents_count = (
        db.query(func.count(Agent.id))
        .filter(Agent.organization_id == organization_id, Agent.workspace_id == workspace_id)
        .scalar()
        or 0
    )
    personas_count = (
        db.query(func.count(Persona.id))
        .filter(Persona.organization_id == organization_id, Persona.workspace_id == workspace_id)
        .scalar()
        or 0
    )
    scenarios_count = (
        db.query(func.count(Scenario.id))
        .filter(Scenario.organization_id == organization_id, Scenario.workspace_id == workspace_id)
        .scalar()
        or 0
    )
    integrations_count = (
        db.query(func.count(Integration.id))
        .filter(Integration.organization_id == organization_id)
        .scalar()
        or 0
    )
    voice_bundles_count = (
        db.query(func.count(VoiceBundle.id))
        .filter(VoiceBundle.organization_id == organization_id)
        .scalar()
        or 0
    )

    recent_evaluations = (
        db.query(Evaluation)
        .filter(
            Evaluation.organization_id == organization_id,
            Evaluation.workspace_id == workspace_id,
        )
        .order_by(Evaluation.created_at.desc())
        .limit(5)
        .all()
    )

    metric_filters = _metric_filters(organization_id, workspace_id)
    metrics_total = db.query(func.count(Metric.id)).filter(*metric_filters).scalar() or 0
    metrics_enabled = (
        db.query(func.count(Metric.id))
        .filter(*metric_filters, Metric.enabled == True)
        .scalar()
        or 0
    )

    call_imports_total = (
        db.query(func.count(CallImport.id))
        .filter(
            CallImport.organization_id == organization_id,
            CallImport.workspace_id == workspace_id,
        )
        .scalar()
        or 0
    )

    call_import_eval_counts = _count_call_import_evaluations(
        db, organization_id, workspace_id
    )

    return DashboardSummaryResponse(
        evaluations=eval_counts,
        resources=ResourceCounts(
            agents=agents_count,
            personas=personas_count,
            scenarios=scenarios_count,
            integrations=integrations_count,
            voice_bundles=voice_bundles_count,
        ),
        setup_progress=SetupProgress(
            has_integration=integrations_count > 0,
            has_voice_bundle=voice_bundles_count > 0,
            has_agent=agents_count > 0,
            has_evaluation=eval_counts.total > 0,
        ),
        metrics=MetricCounts(total=metrics_total, enabled=metrics_enabled),
        call_imports=CallImportCounts(total=call_imports_total),
        call_import_evaluations=call_import_eval_counts,
        recent_evaluations=recent_evaluations,
    )
