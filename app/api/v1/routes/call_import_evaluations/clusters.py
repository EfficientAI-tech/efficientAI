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
    _completed_row_pairs_for_evaluation,
    _load_eval_rows,
    _metrics_for_ids,
    _require_import,
)
from app.api.v1.routes.call_import_evaluations.aggregate import (  # noqa: E402
    _child_names_by_parent,
    _clustering_context,
    _compute_metric_aggregates,
    _metric_is_user_insight,
)

def _metrics_for_clustering(
    db: Session,
    evaluation: CallImportEvaluation,
    eval_rows: List[CallImportEvaluationRow],
) -> List[Metric]:
    """All enabled quality metrics scored in this run, normalized for clustering.

    Hierarchical children are collapsed to their parent metric so cluster
    groups render at the category level (e.g. ``AI reveal``) instead of the
    child label level (e.g. ``Yes`` / ``No``).
    """
    aggregates = _compute_metric_aggregates(db, evaluation, eval_rows)
    aggregate_metric_ids: List[UUID] = []
    for agg in aggregates:
        if (agg.metric_category or "quality") == "user_insight":
            continue
        try:
            aggregate_metric_ids.append(UUID(agg.metric_id))
        except (TypeError, ValueError):
            continue
    if not aggregate_metric_ids:
        return []

    aggregate_metrics = _metrics_for_ids(
        db, evaluation.organization_id, aggregate_metric_ids
    )
    by_id = {metric.id: metric for metric in aggregate_metrics}

    normalized_ids: List[UUID] = []
    seen: set[UUID] = set()
    for metric_id in aggregate_metric_ids:
        metric = by_id.get(metric_id)
        target_id = (
            metric.parent_metric_id
            if metric is not None and metric.parent_metric_id
            else metric_id
        )
        if target_id in seen:
            continue
        seen.add(target_id)
        normalized_ids.append(target_id)

    metrics = _metrics_for_ids(db, evaluation.organization_id, normalized_ids)
    return [
        metric
        for metric in metrics
        if getattr(metric, "enabled", True) and not _metric_is_user_insight(metric)
    ]
def _metric_clusters_payload(
    evaluation: CallImportEvaluation,
) -> Optional[EvaluationMetricClustersState]:
    raw = getattr(evaluation, "metric_clusters", None)
    if raw is None:
        return None
    return metric_clusters_state_from_raw(
        raw,
        completed_rows=evaluation.completed_rows,
    )


def _selected_metric_clusters_for_pdf(
    state: Optional[EvaluationMetricClustersState],
    report_config: dict[str, Any],
) -> dict[str, Any]:
    if state is None or state.status != "completed":
        return {}
    sections = report_config.get("sections")
    if isinstance(sections, dict) and sections.get("failure_diagnostics") is False:
        return {}
    payload: dict[str, Any] = {
        "groups": [g.model_dump(mode="json") for g in state.groups],
        "discovered_problems": [
            d.model_dump(mode="json") for d in state.discovered_problems
        ],
    }
    if state.rca_summary is not None:
        payload["rca_summary"] = state.rca_summary.model_dump(mode="json")
    return payload
def _resolve_metric_cluster_row_selection(
    db: Session,
    evaluation: CallImportEvaluation,
    eval_rows: List[CallImportEvaluationRow],
    evaluation_row_ids: Optional[List[UUID]],
    *,
    row_limit: Optional[int] = None,
    policies: Optional[Dict[str, MetricFailurePolicy]] = None,
) -> Tuple[List[Tuple[CallImportEvaluationRow, CallImportRow]], List[str]]:
    """Return filtered completed row pairs and the selected row id strings."""
    completed_pairs = _completed_row_pairs_for_evaluation(db, evaluation.id)
    metrics = _metrics_for_clustering(db, evaluation, eval_rows)
    if policies is None:
        aggregates = _compute_metric_aggregates(db, evaluation, eval_rows)
        parent_ids = [
            m.id
            for m in metrics
            if getattr(m, "selection_mode", None)
            and not getattr(m, "parent_metric_id", None)
        ]
        child_names_by_parent = _child_names_by_parent(
            db, evaluation.organization_id, parent_ids
        )
        policies, _ = effective_policies(
            evaluation,
            metrics,
            aggregates,
            child_names_by_parent=child_names_by_parent,
        )
    eligible = list_eligible_cluster_rows(
        evaluation, completed_pairs, metrics, policies
    )
    eligible_ordered_ids = [str(item["evaluation_row_id"]) for item in eligible]
    eligible_id_set = set(eligible_ordered_ids)

    if evaluation_row_ids is None and row_limit is not None:
        selected_ids = eligible_ordered_ids[:row_limit]
        filtered = filter_completed_row_pairs(
            completed_pairs,
            [UUID(rid) for rid in selected_ids],
        )
        return filtered, selected_ids

    if evaluation_row_ids is None:
        selected_ids = eligible_ordered_ids
        filtered = filter_completed_row_pairs(
            completed_pairs,
            [UUID(rid) for rid in selected_ids],
        )
        return filtered, selected_ids

    requested = {str(rid) for rid in evaluation_row_ids}
    completed_id_set = {str(eval_row.id) for eval_row, _ in completed_pairs}
    unknown = sorted(requested - completed_id_set)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                "One or more evaluation_row_ids are missing or not completed: "
                + ", ".join(unknown[:5])
                + ("…" if len(unknown) > 5 else "")
            ),
        )
    not_eligible = sorted(requested - eligible_id_set)
    if not_eligible:
        raise HTTPException(
            status_code=400,
            detail=(
                "Each selected row must have at least one flagged quality metric. "
                "Ineligible row(s): "
                + ", ".join(not_eligible[:5])
                + ("…" if len(not_eligible) > 5 else "")
            ),
        )
    selected_ids = sorted(requested)
    filtered = filter_completed_row_pairs(completed_pairs, evaluation_row_ids)
    return filtered, selected_ids


def _enqueue_metric_clusters_job(
    evaluation: CallImportEvaluation,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    credential_id: Optional[UUID] = None,
    force: bool = False,
    max_llm_calls: Optional[int] = None,
    evaluation_row_ids: Optional[List[UUID]] = None,
    selected_evaluation_row_ids: Optional[List[str]] = None,
    failure_policies: Optional[Dict[str, MetricFailurePolicy]] = None,
    db: Optional[Session] = None,
    principal: Optional[Principal] = None,
) -> None:
    current = _metric_clusters_payload(evaluation)
    if current is not None and current.status == "running" and not force:
        return

    llm_budget = normalize_max_llm_calls(max_llm_calls)
    total_calls = 1
    row_ids_for_task: Optional[List[str]] = None
    if db is not None:
        eval_rows = _load_eval_rows(db, evaluation.id)
        if selected_evaluation_row_ids is None:
            _, selected_evaluation_row_ids = _resolve_metric_cluster_row_selection(
                db,
                evaluation,
                eval_rows,
                evaluation_row_ids,
            )
        completed_pairs = filter_completed_row_pairs(
            _completed_row_pairs_for_evaluation(db, evaluation.id),
            [UUID(rid) for rid in selected_evaluation_row_ids],
        )
        metrics = _metrics_for_clustering(db, evaluation, eval_rows)
        policies_for_estimate = failure_policies
        if policies_for_estimate is None:
            aggregates = _compute_metric_aggregates(db, evaluation, eval_rows)
            parent_ids = [
                m.id
                for m in metrics
                if getattr(m, "selection_mode", None)
                and not getattr(m, "parent_metric_id", None)
            ]
            child_names_by_parent = _child_names_by_parent(
                db, evaluation.organization_id, parent_ids
            )
            policies_for_estimate, _ = effective_policies(
                evaluation,
                metrics,
                aggregates,
                child_names_by_parent=child_names_by_parent,
            )
        _, total_calls = estimate_metric_clusters_llm_calls(
            evaluation,
            metrics,
            completed_pairs,
            policies_for_estimate,
            max_llm_calls=llm_budget,
        )
        row_ids_for_task = list(selected_evaluation_row_ids)

    prior_raw = (
        evaluation.metric_clusters
        if isinstance(evaluation.metric_clusters, dict)
        else {}
    )
    policy_blob: Dict[str, Any] = {}
    if failure_policies:
        policy_blob = failure_policies_to_db(failure_policies, source="user")

    evaluation.metric_clusters = {
        "status": "running",
        "groups": prior_raw.get("groups", []) if isinstance(prior_raw, dict) else [],
        "discovered_problems": (
            prior_raw.get("discovered_problems", [])
            if isinstance(prior_raw, dict)
            else []
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_completed_rows": evaluation.completed_rows,
        "progress": {"completed_llm_calls": 0, "total_llm_calls": total_calls},
        "provider": provider,
        "model": model,
        "max_llm_calls": llm_budget,
        "llm_calls_used": 0,
        "error_message": None,
        "selected_evaluation_row_ids": selected_evaluation_row_ids or [],
        **policy_blob,
    }
    if db is not None:
        if principal is not None:
            stamp_evaluation_actor(evaluation, principal)
        flag_modified(evaluation, "metric_clusters")
        db.commit()

    from app.workers.tasks.generate_evaluation_metric_clusters import (
        generate_evaluation_metric_clusters_task,
    )

    async_result = generate_evaluation_metric_clusters_task.apply_async(
        kwargs={
            "evaluation_id": str(evaluation.id),
            "provider": provider,
            "model": model,
            "credential_id": str(credential_id) if credential_id else None,
            "max_llm_calls": llm_budget,
            "evaluation_row_ids": row_ids_for_task,
        },
        queue="imports",
    )
    if db is not None and isinstance(evaluation.metric_clusters, dict):
        evaluation.metric_clusters["celery_task_id"] = async_result.id
        flag_modified(evaluation, "metric_clusters")
        if principal is not None:
            stamp_evaluation_actor(evaluation, principal)
        db.commit()


def _revoke_metric_clusters_task(evaluation: CallImportEvaluation) -> None:
    """Best-effort SIGTERM revoke of the in-flight clustering Celery task."""
    raw = evaluation.metric_clusters
    if not isinstance(raw, dict):
        return
    task_id = str(raw.get("celery_task_id") or "").strip()
    if not task_id:
        return
    try:
        from app.workers.celery_app import celery_app

        celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        logger.info(
            "Revoked metric-clusters task {} for evaluation {}",
            task_id,
            evaluation.id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to revoke metric-clusters task {} for evaluation {}: {}",
            task_id,
            evaluation.id,
            exc,
        )


def _apply_metric_clusters_cancel(evaluation: CallImportEvaluation) -> bool:
    """Mark clustering as cancelled and revoke the worker task.

    Returns True if a running job was cancelled, False if already terminal.
    """
    raw = evaluation.metric_clusters
    if not isinstance(raw, dict):
        return False
    if (raw.get("status") or "").lower() != "running":
        return False

    _revoke_metric_clusters_task(evaluation)
    progress = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
    evaluation.metric_clusters = {
        **raw,
        "status": "cancelled",
        "error_message": METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR,
        "progress": progress,
        "celery_task_id": None,
    }
    return True


@router.get(
    "/{eval_id}/metric-clusters/failure-policies",
    response_model=MetricFailurePoliciesResponse,
    operation_id="getCallImportEvaluationMetricClusterFailurePolicies",
)
async def get_call_import_evaluation_metric_cluster_failure_policies(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> MetricFailurePoliciesResponse:
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

    eval_rows = _load_eval_rows(db, eval_id)
    metrics, aggregates, policies, source, child_names_by_parent = _clustering_context(
        db, evaluation, eval_rows
    )
    previews = build_failure_policy_previews(
        metrics,
        aggregates,
        child_names_by_parent=child_names_by_parent,
        effective=policies,
    )
    updated_at = None
    raw_mc = evaluation.metric_clusters
    if isinstance(raw_mc, dict) and raw_mc.get("failure_policies_updated_at"):
        try:
            updated_at = datetime.fromisoformat(
                str(raw_mc["failure_policies_updated_at"])
            )
        except ValueError:
            updated_at = None
    return MetricFailurePoliciesResponse(
        previews=previews,
        policies=policies,
        source=source,
        updated_at=updated_at,
    )


@router.put(
    "/{eval_id}/metric-clusters/failure-policies",
    response_model=MetricFailurePoliciesResponse,
    operation_id="saveCallImportEvaluationMetricClusterFailurePolicies",
)
async def save_call_import_evaluation_metric_cluster_failure_policies(
    call_import_id: UUID,
    eval_id: UUID,
    body: MetricFailurePoliciesSaveRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> MetricFailurePoliciesResponse:
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

    eval_rows = _load_eval_rows(db, eval_id)
    metrics, aggregates, _existing, _source, child_names_by_parent = _clustering_context(
        db, evaluation, eval_rows
    )
    try:
        validate_failure_policies_for_metrics(body.policies, metrics)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    prior = (
        evaluation.metric_clusters
        if isinstance(evaluation.metric_clusters, dict)
        else {}
    )
    evaluation.metric_clusters = merge_failure_policies_into_raw(
        prior,
        body.policies,
        source="user",
    )
    flag_modified(evaluation, "metric_clusters")
    stamp_evaluation_actor(evaluation, principal)
    db.commit()
    db.refresh(evaluation)

    policies, source = policies_from_evaluation_raw(evaluation.metric_clusters)
    if source != "user":
        source = "user"
    previews = build_failure_policy_previews(
        metrics,
        aggregates,
        child_names_by_parent=child_names_by_parent,
        effective=policies,
    )
    updated_at = None
    raw_mc = evaluation.metric_clusters
    if isinstance(raw_mc, dict) and raw_mc.get("failure_policies_updated_at"):
        try:
            updated_at = datetime.fromisoformat(
                str(raw_mc["failure_policies_updated_at"])
            )
        except ValueError:
            updated_at = None
    return MetricFailurePoliciesResponse(
        previews=previews,
        policies=policies,
        source="user",
        updated_at=updated_at,
    )


@router.get(
    "/{eval_id}/metric-clusters/eligible-rows",
    response_model=MetricClusterEligibleRowsResponse,
    operation_id="listCallImportEvaluationMetricClusterEligibleRows",
)
async def list_call_import_evaluation_metric_cluster_eligible_rows(
    call_import_id: UUID,
    eval_id: UUID,
    limit: Optional[int] = Query(default=None, ge=1),
    count_only: bool = Query(default=False),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> MetricClusterEligibleRowsResponse:
    """Completed rows that have at least one flagged quality metric."""
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

    eval_rows = _load_eval_rows(db, eval_id)
    completed_pairs = _completed_row_pairs_for_evaluation(db, eval_id)
    metrics, _aggregates, policies, _source, _child_map = _clustering_context(
        db, evaluation, eval_rows
    )
    all_eligible = list_eligible_cluster_rows(
        evaluation, completed_pairs, metrics, policies
    )
    total = len(all_eligible)
    if count_only:
        return MetricClusterEligibleRowsResponse(items=[], total=total)
    raw_items = all_eligible if limit is None else all_eligible[:limit]
    items = [MetricClusterEligibleRow.model_validate(item) for item in raw_items]
    return MetricClusterEligibleRowsResponse(items=items, total=total)


@router.get(
    "/{eval_id}/metric-clusters",
    response_model=Optional[EvaluationMetricClustersState],
    operation_id="getCallImportEvaluationMetricClusters",
)
async def get_call_import_evaluation_metric_clusters(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Optional[EvaluationMetricClustersState]:
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
    return _metric_clusters_payload(evaluation)


@router.post(
    "/{eval_id}/metric-clusters",
    response_model=EvaluationMetricClustersState,
    operation_id="generateCallImportEvaluationMetricClusters",
)
async def generate_call_import_evaluation_metric_clusters(
    call_import_id: UUID,
    eval_id: UUID,
    body: EvaluationMetricClustersRequest = Body(
        default_factory=EvaluationMetricClustersRequest
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> EvaluationMetricClustersState:
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

    if not body.regenerate and not body.force:
        cached = _metric_clusters_payload(evaluation)
        if cached is not None and cached.status in {"running", "completed"}:
            return cached

    eval_rows = _load_eval_rows(db, eval_id)
    if not any(row.status == "completed" for row in eval_rows):
        raise HTTPException(
            status_code=400,
            detail=(
                "No completed rows yet. Wait for at least one row to "
                "finish scoring before generating metric clusters."
            ),
        )

    if body.evaluation_row_ids and body.row_limit is not None:
        raise HTTPException(
            status_code=400,
            detail="Specify either evaluation_row_ids or row_limit, not both.",
        )

    if body.evaluation_row_ids:
        completed_pairs = _completed_row_pairs_for_evaluation(db, evaluation.id)
        completed_id_set = {str(eval_row.id) for eval_row, _ in completed_pairs}
        requested = {str(rid) for rid in body.evaluation_row_ids}
        unknown = sorted(requested - completed_id_set)
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=(
                    "One or more evaluation_row_ids are missing or not completed: "
                    + ", ".join(unknown[:5])
                    + ("…" if len(unknown) > 5 else "")
                ),
            )

    from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request

    provider_enum, model_str = get_llm_provider_and_model_for_request(
        organization_id, db, body.provider, body.model, body.credential_id
    )

    metrics, aggregates, _inferred, _source, child_names_by_parent = _clustering_context(
        db, evaluation, eval_rows
    )
    merged_policies = merge_clustering_policies(
        body.failure_policies,
        evaluation,
        metrics,
        aggregates,
        child_names_by_parent=child_names_by_parent,
    )
    try:
        validate_failure_policies_for_metrics(
            body.failure_policies or merged_policies, metrics
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not has_clusterable_metrics(metrics, merged_policies, eval_rows):
        raise HTTPException(
            status_code=400,
            detail=(
                "No calls match any failure policy. Select failure values on "
                "metrics that have matching rows, or leave metrics with no "
                "failures unchecked — they are skipped automatically."
            ),
        )

    filtered_pairs, selected_row_ids = _resolve_metric_cluster_row_selection(
        db,
        evaluation,
        eval_rows,
        body.evaluation_row_ids,
        row_limit=body.row_limit,
        policies=merged_policies,
    )
    if not selected_row_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                "No eligible rows to cluster. Select completed calls that match "
                "at least one configured failure policy."
            ),
        )
    if not filtered_pairs:
        raise HTTPException(
            status_code=400,
            detail="No completed rows match the selected evaluation_row_ids.",
        )

    _enqueue_metric_clusters_job(
        evaluation,
        provider=provider_enum.value,
        model=model_str,
        credential_id=body.credential_id,
        force=body.force or body.regenerate,
        max_llm_calls=body.max_llm_calls,
        evaluation_row_ids=body.evaluation_row_ids,
        selected_evaluation_row_ids=selected_row_ids,
        failure_policies=merged_policies,
        db=db,
        principal=principal,
    )

    db.refresh(evaluation)
    return _metric_clusters_payload(evaluation) or EvaluationMetricClustersState(
        status="running"
    )


@router.post(
    "/{eval_id}/metric-clusters/cancel",
    response_model=EvaluationMetricClustersState,
    operation_id="cancelCallImportEvaluationMetricClusters",
)
async def cancel_call_import_evaluation_metric_clusters(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> EvaluationMetricClustersState:
    """Abort in-flight failure-diagnostics clustering.

    Idempotent: if clustering is not ``running``, returns the current state
    unchanged.
    """
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

    _apply_metric_clusters_cancel(evaluation)
    flag_modified(evaluation, "metric_clusters")
    stamp_evaluation_actor(evaluation, principal)
    db.commit()
    db.refresh(evaluation)

    return _metric_clusters_payload(evaluation) or EvaluationMetricClustersState(
        status="idle"
    )
