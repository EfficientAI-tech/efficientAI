"""Evaluation routes scoped to a Call Import batch."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re
import statistics
from typing import Any, Dict, Iterator, List, Literal, Optional, Set, Tuple
from uuid import UUID, uuid4

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Float, case, cast, desc, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.auth import Principal, get_principal
from app.core.auth.capabilities import REPORTS_GENERATE, capability_denied_message
from app.database import get_db
from app.dependencies import (
    get_api_key,
    get_organization_id,
    get_workspace_id,
    require_enterprise_feature,
)
from app.services.call_imports.audit import (
    actor_emails_for_evaluation,
    emails_for_user_ids,
    stamp_call_import_actor,
    stamp_evaluation_actor,
    user_ids_from_evaluations,
)
from app.services.workspace_rbac import resolve_workspace_capabilities
from app.models.database import (
    AIProvider,
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationReportSnapshot,
    CallImportEvaluationPdfReport,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    PromptPartial,
    Workspace,
)
from app.models.enums import CallImportRowStatus, ModelProvider
from app.models.schemas import (
    CallImportEvaluationAggregateResponse,
    CallImportEvaluationBulkDelete,
    CallImportEvaluationBulkActionResponse,
    CallImportEvaluationCreate,
    CallImportEvaluationExportJobResponse,
    CallImportEvaluationExportRequest,
    CallImportEvaluationListResponse,
    CallImportEvaluationResponse,
    CallImportEvaluationRetryRequest,
    CallImportEvaluationRetryResponse,
    CallImportEvaluationRetrySkippedItem,
    CallImportEvaluationRowListResponse,
    CallImportEvaluationRowResponse,
    CallImportEvaluationUpdate,
    CallImportClassificationFacetCounts,
    CallImportMetricAggregate,
    CallImportMetricHistogramBucket,
    CallImportMetricLabelPair,
    CallImportMetricSummary,
    CallImportMetricValueCount,
    DiscoveredLabelDeleteRequest,
    DiscoveredLabelItem,
    DiscoveredLabelMergeRequest,
    DiscoveredLabelsResponse,
    DiscoveredMetricDeleteRequest,
    DiscoveredMetricItem,
    DiscoveredMetricMergeRequest,
    DiscoveredMetricsResponse,
    EvaluationInsightsRequest,
    EvaluationTldrSummary,
    EvaluationMetricClustersRequest,
    EvaluationMetricClustersState,
    EvaluationPromptImprovementsRequest,
    EvaluationPromptImprovementsState,
    PromptImprovementReviewUpdate,
    PromptPushConfirm,
    PromptPushPreviewResponse,
    PromptPushResponse,
    MetricFailurePoliciesResponse,
    MetricFailurePoliciesSaveRequest,
    MetricFailurePolicy,
    MetricClusterEligibleRow,
    MetricClusterEligibleRowsResponse,
    EvaluationUserInsightsRequest,
    EvaluationUserInsightsState,
    MetricFlowEdge,
    MetricPeriodDelta,
    MetricFlowNode,
    MetricFlowResponse,
)
from app.services.reporting.call_import_evaluation_pdf_report import (
    call_import_evaluation_pdf_report_service,
)
from app.services.reporting.call_import_pdf_report_storage import (
    build_pdf_report_s3_key,
    compute_pdf_report_cache_fingerprint,
    compute_pdf_report_config_fingerprint,
    compute_pdf_report_content_fingerprint,
    config_summary_from_report_config,
    find_cached_pdf_report,
    presigned_urls_for_pdf_report,
)
from app.services.call_import_metric_clusters import (
    METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR,
    estimate_metric_clusters_llm_calls,
    filter_completed_row_pairs,
    list_eligible_cluster_rows,
    metric_clusters_raw_is_cancelled,
    metric_clusters_state_from_raw,
    metric_clusters_state_to_db,
)
from app.services.classification_metric_scores import classification_facets_from_entry
from app.services.classification_metric_sql import (
    classification_choice_row_predicate,
    classification_level_row_predicate,
)
from app.services.metric_classification_validation import is_classification_metric
from app.services.metric_failure_policy import (
    aggregate_primary_percent,
    build_failure_policy_previews,
    effective_policies,
    failure_rate_percent_from_rows,
    failure_policies_to_db,
    has_clusterable_metrics,
    merge_clustering_policies,
    merge_failure_policies_into_raw,
    policies_from_evaluation_raw,
    validate_failure_policies_for_metrics,
)
from app.services.call_import_user_insights import (
    normalize_max_llm_calls,
    total_llm_calls_for_rows,
    user_insights_state_from_raw,
)

from app.api.v1.routes.call_import_evaluations._router import router

from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _require_import,
)
from app.api.v1.routes.call_import_evaluations.clusters import (  # noqa: E402
    _metric_clusters_payload,
)
from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    require_call_import_capability,
)

def _prompt_improvements_payload(
    evaluation: CallImportEvaluation,
) -> Optional[EvaluationPromptImprovementsState]:
    from app.services.call_import_prompt_improvements import (
        prompt_improvements_state_from_raw,
    )

    raw = getattr(evaluation, "prompt_improvements", None)
    if raw is None:
        return None
    return prompt_improvements_state_from_raw(
        raw,
        completed_rows=evaluation.completed_rows,
    )


def _selected_prompt_improvements_for_pdf(
    state: Optional[EvaluationPromptImprovementsState],
    report_config: dict[str, Any],
) -> dict[str, Any]:
    if state is None or state.status != "completed":
        return {}
    sections = report_config.get("sections")
    if isinstance(sections, dict) and sections.get("prompt_improvements") is False:
        return {}
    return {
        "imported_agent_id": state.imported_agent_id,
        "imported_agent_name": state.imported_agent_name,
        "overview": state.overview,
        "suggestions": [s.model_dump(mode="json") for s in state.suggestions],
    }


def _enqueue_prompt_improvements_job(
    evaluation: CallImportEvaluation,
    *,
    imported_agent_id: UUID,
    imported_agent_name: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    credential_id: Optional[UUID] = None,
    force: bool = False,
    db: Optional[Session] = None,
    principal: Optional[Principal] = None,
) -> None:
    current = _prompt_improvements_payload(evaluation)
    if current is not None and current.status == "running" and not force:
        return

    evaluation.prompt_improvements = {
        "status": "running",
        "imported_agent_id": str(imported_agent_id),
        "imported_agent_name": imported_agent_name,
        "suggestions": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_completed_rows": evaluation.completed_rows,
        "provider": provider,
        "model": model,
        "error_message": None,
    }
    if db is not None:
        if principal is not None:
            stamp_evaluation_actor(evaluation, principal)
        flag_modified(evaluation, "prompt_improvements")
        db.commit()

    from app.workers.tasks.generate_evaluation_prompt_improvements import (
        generate_evaluation_prompt_improvements_task,
    )

    async_result = generate_evaluation_prompt_improvements_task.apply_async(
        kwargs={
            "evaluation_id": str(evaluation.id),
            "imported_agent_id": str(imported_agent_id),
            "provider": provider,
            "model": model,
            "credential_id": str(credential_id) if credential_id else None,
        },
        queue="imports",
    )
    if db is not None and isinstance(evaluation.prompt_improvements, dict):
        evaluation.prompt_improvements["celery_task_id"] = async_result.id
        flag_modified(evaluation, "prompt_improvements")
        db.commit()


@router.get(
    "/{eval_id}/prompt-improvements",
    response_model=Optional[EvaluationPromptImprovementsState],
    operation_id="getCallImportEvaluationPromptImprovements",
)
async def get_call_import_evaluation_prompt_improvements(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Optional[EvaluationPromptImprovementsState]:
    del api_key
    _require_import(db, call_import_id, organization_id)

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not evaluation:
        raise HTTPException(
            status_code=404, detail="Call import evaluation not found"
        )
    return _prompt_improvements_payload(evaluation)


@router.post(
    "/{eval_id}/prompt-improvements",
    response_model=EvaluationPromptImprovementsState,
    operation_id="generateCallImportEvaluationPromptImprovements",
)
async def generate_call_import_evaluation_prompt_improvements(
    call_import_id: UUID,
    eval_id: UUID,
    body: EvaluationPromptImprovementsRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> EvaluationPromptImprovementsState:
    del api_key
    _require_import(db, call_import_id, organization_id)

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not evaluation:
        raise HTTPException(
            status_code=404, detail="Call import evaluation not found"
        )

    clusters = _metric_clusters_payload(evaluation)
    if clusters is None or clusters.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=(
                "Metric clusters must be completed before generating prompt "
                "improvements. Run failure diagnostics first."
            ),
        )

    from app.services.call_import_prompt_improvements import is_imported_agent
    from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request
    from app.services.platform_import_imported_agent import resolve_imported_agent_for_call_import

    call_import = _require_import(db, call_import_id, organization_id)
    imported_agent_id = body.imported_agent_id
    if imported_agent_id is None:
        linked = resolve_imported_agent_for_call_import(db, call_import, principal)
        if linked is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No imported agent is linked to this import. Select an imported agent "
                    "or use a single-agent platform import."
                ),
            )
        imported_agent_id = linked.id

    imported_agent = (
        db.query(PromptPartial)
        .filter(
            PromptPartial.id == imported_agent_id,
            PromptPartial.organization_id == organization_id,
            PromptPartial.workspace_id == workspace_id,
        )
        .first()
    )
    if imported_agent is None or not is_imported_agent(imported_agent):
        from app.services.platform_import_imported_agent import (
            relink_evaluation_imported_agent,
            resolve_imported_agent_for_call_import,
        )

        recovered = resolve_imported_agent_for_call_import(db, call_import, principal)
        if recovered is None or not is_imported_agent(recovered):
            raise HTTPException(
                status_code=404,
                detail="Imported agent not found in the active workspace",
            )
        imported_agent = recovered
        imported_agent_id = recovered.id
        if isinstance(evaluation.prompt_improvements, dict):
            relink_evaluation_imported_agent(evaluation, recovered)
            stamp_evaluation_actor(evaluation, principal)
            db.commit()

    if not body.regenerate and not body.force:
        cached = _prompt_improvements_payload(evaluation)
        if (
            cached is not None
            and cached.status in {"running", "completed"}
            and cached.imported_agent_id == str(imported_agent_id)
        ):
            return cached

    provider_enum, model_str = get_llm_provider_and_model_for_request(
        organization_id, db, body.provider, body.model, body.credential_id
    )

    _enqueue_prompt_improvements_job(
        evaluation,
        imported_agent_id=imported_agent_id,
        imported_agent_name=imported_agent.name,
        provider=provider_enum.value,
        model=model_str,
        credential_id=body.credential_id,
        force=body.force or body.regenerate,
        db=db,
        principal=principal,
    )

    db.refresh(evaluation)
    return _prompt_improvements_payload(evaluation) or EvaluationPromptImprovementsState(
        status="running",
        imported_agent_id=str(imported_agent_id),
        imported_agent_name=imported_agent.name,
    )


def _load_evaluation_for_prompt_push(
    db: Session,
    call_import_id: UUID,
    eval_id: UUID,
    organization_id: UUID,
) -> tuple[CallImport, CallImportEvaluation]:
    call_import = _require_import(db, call_import_id, organization_id)
    evaluation = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not evaluation:
        raise HTTPException(status_code=404, detail="Call import evaluation not found")
    return call_import, evaluation


@router.patch(
    "/{eval_id}/prompt-improvements/review",
    response_model=EvaluationPromptImprovementsState,
    operation_id="reviewCallImportEvaluationPromptImprovement",
)
async def review_call_import_evaluation_prompt_improvement(
    call_import_id: UUID,
    eval_id: UUID,
    body: PromptImprovementReviewUpdate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> EvaluationPromptImprovementsState:
    del api_key
    from app.services.call_import_prompt_push import PromptPushError, set_suggestion_review

    _, evaluation = _load_evaluation_for_prompt_push(db, call_import_id, eval_id, organization_id)
    try:
        set_suggestion_review(evaluation, body.suggestion_id, body.review_status, body.edited_text)
    except PromptPushError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    stamp_evaluation_actor(evaluation, principal)
    db.commit()
    db.refresh(evaluation)
    return _prompt_improvements_payload(evaluation) or EvaluationPromptImprovementsState(status="idle")


@router.get(
    "/{eval_id}/prompt-improvements/push-preview",
    response_model=PromptPushPreviewResponse,
    operation_id="previewCallImportEvaluationPromptPush",
)
async def preview_call_import_evaluation_prompt_push(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> PromptPushPreviewResponse:
    del api_key
    from app.services.call_import_prompt_push import PromptPushError, preview_evaluation_push

    call_import, evaluation = _load_evaluation_for_prompt_push(
        db, call_import_id, eval_id, organization_id
    )
    try:
        payload = preview_evaluation_push(
            db, evaluation, call_import, organization_id, workspace_id
        )
    except PromptPushError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return PromptPushPreviewResponse(**payload)


@router.post(
    "/{eval_id}/prompt-improvements/push",
    response_model=PromptPushResponse,
    operation_id="pushCallImportEvaluationPrompt",
)
async def push_call_import_evaluation_prompt(
    call_import_id: UUID,
    eval_id: UUID,
    body: PromptPushConfirm,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> PromptPushResponse:
    del api_key
    from app.services.call_import_prompt_push import PromptPushError, push_evaluation_prompt

    call_import, evaluation = _load_evaluation_for_prompt_push(
        db, call_import_id, eval_id, organization_id
    )
    try:
        row = push_evaluation_prompt(
            db,
            evaluation,
            call_import,
            organization_id,
            workspace_id,
            body.confirm,
            principal,
            push_to_live=body.push_to_live,
        )
    except PromptPushError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return row

