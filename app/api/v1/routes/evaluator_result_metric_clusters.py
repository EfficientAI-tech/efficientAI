"""Metric-cluster routes for filtered evaluator-result scopes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.dependencies import get_organization_id, get_workspace_id, require_enterprise_feature
from app.models.schemas import (
    EvaluationMetricClustersRequest,
    EvaluationMetricClustersState,
    EvaluatorResultClusterScopeListResponse,
    MetricClusterEligibleRow,
    MetricClusterEligibleRowsResponse,
    MetricFailurePoliciesResponse,
    MetricFailurePoliciesSaveRequest,
)
from app.services.call_import_metric_clusters import (
    build_metric_cluster_progress,
    estimate_metric_clusters_llm_calls_for_source_rows,
    list_eligible_cluster_source_rows,
    metric_clusters_state_from_raw,
)
from app.services.call_import_user_insights import normalize_max_llm_calls
from app.services.evaluators.evaluator_result_metric_clusters import (
    apply_metric_clusters_cancel,
    build_generation_scope_snapshot,
    clustering_context_for_job,
    count_completed_evaluator_results_for_job,
    delete_cluster_job,
    failure_policies_response_for_job,
    get_cluster_job_by_id,
    get_cluster_job_by_scope_key,
    get_or_create_cluster_job,
    has_clusterable_evaluator_results,
    load_completed_evaluator_results,
    list_evaluator_result_cluster_scopes,
    metric_clusters_payload,
    resolve_source_row_selection,
)
from app.services.metric_failure_policy import (
    merge_clustering_policies_from_raw,
    merge_failure_policies_into_raw,
    validate_failure_policies_for_metrics,
)

router = APIRouter(
    prefix="/evaluator-results/metric-clusters",
    tags=["evaluator-results"],
    dependencies=[Depends(require_enterprise_feature("evaluation_clustering"))],
)


def _parse_datetime_param(value: Optional[str], *, field_name: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_cluster_scope(
    agent_id: Optional[str],
    scenario_ids: Optional[List[str]],
    since: Optional[str],
    until: Optional[str],
    suite_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
) -> tuple[UUID, Optional[List[UUID]], Optional[datetime], Optional[datetime], Optional[UUID], Optional[UUID]]:
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    try:
        agent_uuid = UUID(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid agent_id") from exc

    scenario_uuid_list: Optional[List[UUID]] = None
    if scenario_ids:
        scenario_uuid_list = []
        for raw_id in scenario_ids:
            try:
                scenario_uuid_list.append(UUID(raw_id))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid scenario_id") from exc

    since_dt = _parse_datetime_param(since, field_name="since")
    until_dt = _parse_datetime_param(until, field_name="until")

    suite_uuid: Optional[UUID] = None
    scenario_uuid: Optional[UUID] = None
    if suite_id:
        try:
            suite_uuid = UUID(suite_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid suite_id") from exc
    if scenario_id:
        try:
            scenario_uuid = UUID(scenario_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid scenario_id") from exc

    return agent_uuid, scenario_uuid_list, since_dt, until_dt, suite_uuid, scenario_uuid


def _get_job(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: Optional[str] = None,
    scenario_ids: Optional[List[str]] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    suite_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    scope_key: Optional[str] = None,
    job_id: Optional[str] = None,
):
    if job_id:
        try:
            job_uuid = UUID(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid job_id") from exc
        job = get_cluster_job_by_id(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            job_id=job_uuid,
        )
        if job is None:
            raise HTTPException(status_code=404, detail="Cluster report not found")
        return job

    if scope_key:
        job = get_cluster_job_by_scope_key(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            scope_key=scope_key,
        )
        if job is None:
            raise HTTPException(status_code=404, detail="Cluster report not found")
        return job

    (
        agent_uuid,
        scenario_uuid_list,
        since_dt,
        until_dt,
        suite_uuid,
        scenario_uuid,
    ) = _parse_cluster_scope(
        agent_id,
        scenario_ids,
        since,
        until,
        suite_id=suite_id,
        scenario_id=scenario_id,
    )
    return get_or_create_cluster_job(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_uuid,
        scenario_ids=scenario_uuid_list,
        since=since_dt,
        until=until_dt,
        suite_id=suite_uuid,
        scenario_id=scenario_uuid,
    )


def _revoke_cluster_task(job) -> None:
    from loguru import logger

    raw = job.metric_clusters
    if not isinstance(raw, dict):
        return
    task_id = str(raw.get("celery_task_id") or "").strip()
    if not task_id:
        return
    try:
        from app.workers.celery_app import celery_app

        celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        logger.info("Revoked evaluator metric-clusters task {} for job {}", task_id, job.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to revoke evaluator metric-clusters task {} for job {}: {}",
            task_id,
            job.id,
            exc,
        )


def _enqueue_cluster_job(
    db: Session,
    job,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    credential_id: Optional[UUID] = None,
    force: bool = False,
    max_llm_calls: Optional[int] = None,
    evaluation_row_ids: Optional[List[UUID]] = None,
    selected_evaluation_row_ids: Optional[List[str]] = None,
    failure_policies: Optional[Dict[str, Any]] = None,
    row_limit: Optional[int] = None,
) -> None:
    current = metric_clusters_payload(job)
    if current is not None and current.status == "running" and not force:
        return

    llm_budget = normalize_max_llm_calls(max_llm_calls)
    total_calls = 1
    row_ids_for_task: Optional[List[str]] = None

    if selected_evaluation_row_ids is None:
        try:
            _filtered, selected_evaluation_row_ids = resolve_source_row_selection(
                db,
                job,
                evaluation_row_ids=evaluation_row_ids,
                row_limit=row_limit,
                policies=failure_policies,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    metrics, _aggregates, policies_for_estimate, _source, _child_map, source_rows, _ = (
        clustering_context_for_job(db, job)
    )
    if failure_policies:
        policies_for_estimate = failure_policies
    filtered_rows, _ = resolve_source_row_selection(
        db,
        job,
        evaluation_row_ids=[UUID(rid) for rid in selected_evaluation_row_ids],
        policies=policies_for_estimate,
    )
    _, total_calls = estimate_metric_clusters_llm_calls_for_source_rows(
        job.id,
        metrics,
        filtered_rows,
        policies_for_estimate,
        max_llm_calls=llm_budget,
    )
    row_ids_for_task = list(selected_evaluation_row_ids)

    prior_raw = job.metric_clusters if isinstance(job.metric_clusters, dict) else {}
    policy_blob: Dict[str, Any] = {}
    if failure_policies:
        from app.services.metric_failure_policy import failure_policies_to_db

        policy_blob = failure_policies_to_db(failure_policies, source="user")

    from app.services.evaluators.evaluator_result_metric_clusters import _load_scope_kwargs

    scope = _load_scope_kwargs(job)
    scenario_uuid_list = (
        [UUID(sid) for sid in scope["scenario_ids"]] if scope["scenario_ids"] else None
    )
    completed_count = len(
        load_completed_evaluator_results(
            db,
            organization_id=job.organization_id,
            workspace_id=job.workspace_id,
            agent_id=scope["agent_id"],
            suite_id=scope["suite_id"],
            scenario_id=scope["scenario_id"],
            scenario_ids=scenario_uuid_list,
            since=scope["since"],
            until=scope["until"],
        )
    )

    selected_count = len(selected_evaluation_row_ids or [])
    all_eligible = list_eligible_cluster_source_rows(
        source_rows, metrics, policies_for_estimate
    )
    eligible_count = len(all_eligible)
    generation_scope = build_generation_scope_snapshot(
        db,
        job=job,
        eligible_call_count=eligible_count,
        selected_call_count=selected_count,
    )
    job.metric_clusters = {
        "status": "running",
        "groups": prior_raw.get("groups", []) if isinstance(prior_raw, dict) else [],
        "discovered_problems": (
            prior_raw.get("discovered_problems", []) if isinstance(prior_raw, dict) else []
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_completed_rows": completed_count,
        "progress": build_metric_cluster_progress(
            completed_llm_calls=0,
            total_llm_calls=total_calls,
            completed_selected_calls=0,
            total_selected_calls=selected_count,
        ),
        "provider": provider,
        "model": model,
        "max_llm_calls": llm_budget,
        "llm_calls_used": 0,
        "error_message": None,
        "selected_evaluation_row_ids": selected_evaluation_row_ids or [],
        "generation_scope": generation_scope,
        **policy_blob,
    }
    flag_modified(job, "metric_clusters")
    db.commit()

    from app.workers.tasks.generate_evaluator_result_metric_clusters import (
        generate_evaluator_result_metric_clusters_task,
    )

    async_result = generate_evaluator_result_metric_clusters_task.apply_async(
        kwargs={
            "cluster_job_id": str(job.id),
            "provider": provider,
            "model": model,
            "credential_id": str(credential_id) if credential_id else None,
            "max_llm_calls": llm_budget,
            "evaluation_row_ids": row_ids_for_task,
        },
        queue="evaluations",
    )
    if isinstance(job.metric_clusters, dict):
        job.metric_clusters["celery_task_id"] = async_result.id
        flag_modified(job, "metric_clusters")
        db.commit()


def _cluster_scope_query_params(
    agent_id: Optional[str] = Query(None),
    scenario_ids: Optional[List[str]] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    suite_id: Optional[str] = Query(None),
    scenario_id: Optional[str] = Query(None),
    scope_key: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
):
    return {
        "agent_id": agent_id,
        "scenario_ids": scenario_ids,
        "since": since,
        "until": until,
        "suite_id": suite_id,
        "scenario_id": scenario_id,
        "scope_key": scope_key,
        "job_id": job_id,
    }


@router.get(
    "/failure-policies",
    response_model=MetricFailurePoliciesResponse,
    operation_id="getEvaluatorResultMetricClusterFailurePolicies",
)
def get_evaluator_result_metric_cluster_failure_policies(
    scope: dict = Depends(_cluster_scope_query_params),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> MetricFailurePoliciesResponse:
    job = _get_job(db, organization_id, workspace_id, **scope)
    db.commit()
    return failure_policies_response_for_job(db, job)


@router.put(
    "/failure-policies",
    response_model=MetricFailurePoliciesResponse,
    operation_id="saveEvaluatorResultMetricClusterFailurePolicies",
)
def save_evaluator_result_metric_cluster_failure_policies(
    body: MetricFailurePoliciesSaveRequest,
    scope: dict = Depends(_cluster_scope_query_params),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> MetricFailurePoliciesResponse:
    job = _get_job(db, organization_id, workspace_id, **scope)
    metrics, aggregates, _existing, _source, child_names_by_parent, _rows, _ = (
        clustering_context_for_job(db, job)
    )
    try:
        validate_failure_policies_for_metrics(body.policies, metrics)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    prior = job.metric_clusters if isinstance(job.metric_clusters, dict) else {}
    job.metric_clusters = merge_failure_policies_into_raw(
        prior,
        body.policies,
        source="user",
    )
    flag_modified(job, "metric_clusters")
    db.commit()
    db.refresh(job)
    return failure_policies_response_for_job(db, job)


@router.get(
    "/eligible-rows",
    response_model=MetricClusterEligibleRowsResponse,
    operation_id="listEvaluatorResultMetricClusterEligibleRows",
)
def list_evaluator_result_metric_cluster_eligible_rows(
    scope: dict = Depends(_cluster_scope_query_params),
    limit: Optional[int] = Query(default=None, ge=1),
    count_only: bool = Query(default=False),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> MetricClusterEligibleRowsResponse:
    from app.services.call_import_metric_clusters import list_eligible_cluster_source_rows

    job = _get_job(db, organization_id, workspace_id, **scope)
    metrics, _aggregates, policies, _source, _child_map, source_rows, _ = (
        clustering_context_for_job(db, job)
    )
    all_eligible = list_eligible_cluster_source_rows(source_rows, metrics, policies)
    total = len(all_eligible)
    if count_only:
        return MetricClusterEligibleRowsResponse(items=[], total=total)
    raw_items = all_eligible if limit is None else all_eligible[:limit]
    items = [MetricClusterEligibleRow.model_validate(item) for item in raw_items]
    return MetricClusterEligibleRowsResponse(items=items, total=total)


@router.get(
    "/scopes",
    response_model=EvaluatorResultClusterScopeListResponse,
    operation_id="listEvaluatorResultMetricClusterScopes",
)
def list_evaluator_result_metric_cluster_scopes(
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> EvaluatorResultClusterScopeListResponse:
    items = list_evaluator_result_cluster_scopes(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return EvaluatorResultClusterScopeListResponse(items=items)


@router.get(
    "",
    response_model=Optional[EvaluationMetricClustersState],
    operation_id="getEvaluatorResultMetricClusters",
)
def get_evaluator_result_metric_clusters(
    scope: dict = Depends(_cluster_scope_query_params),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> Optional[EvaluationMetricClustersState]:
    if not scope.get("job_id") and not scope.get("scope_key") and not scope.get("agent_id"):
        raise HTTPException(status_code=400, detail="agent_id is required")
    job = _get_job(db, organization_id, workspace_id, **scope)
    db.commit()
    state = metric_clusters_payload(job)
    if state is None:
        return None
    completed_count = count_completed_evaluator_results_for_job(db, job)
    if state.generated_at_completed_rows and completed_count > state.generated_at_completed_rows:
        state.is_stale = True
    return state


@router.post(
    "",
    response_model=EvaluationMetricClustersState,
    operation_id="generateEvaluatorResultMetricClusters",
)
def generate_evaluator_result_metric_clusters(
    body: EvaluationMetricClustersRequest = Body(default_factory=EvaluationMetricClustersRequest),
    scope: dict = Depends(_cluster_scope_query_params),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> EvaluationMetricClustersState:
    job = _get_job(db, organization_id, workspace_id, **scope)
    db.commit()

    if not body.regenerate and not body.force:
        cached = metric_clusters_payload(job)
        if cached is not None and cached.status in {"running", "completed"}:
            return cached

    from app.services.evaluators.evaluator_result_metric_clusters import _load_scope_kwargs

    scope_kwargs = _load_scope_kwargs(job)
    scenario_uuid_list = (
        [UUID(sid) for sid in scope_kwargs["scenario_ids"]]
        if scope_kwargs["scenario_ids"]
        else None
    )
    completed = load_completed_evaluator_results(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=scope_kwargs["agent_id"],
        suite_id=scope_kwargs["suite_id"],
        scenario_id=scope_kwargs["scenario_id"],
        scenario_ids=scenario_uuid_list,
        since=scope_kwargs["since"],
        until=scope_kwargs["until"],
    )
    if not completed:
        raise HTTPException(
            status_code=400,
            detail=(
                "No completed evaluator results in this scope yet. "
                "Wait for at least one run to finish scoring before generating clusters."
            ),
        )

    if body.evaluation_row_ids and body.row_limit is not None:
        raise HTTPException(
            status_code=400,
            detail="Specify either evaluation_row_ids or row_limit, not both.",
        )

    metrics, aggregates, _inferred, _source, child_names_by_parent, _rows, _ = (
        clustering_context_for_job(db, job)
    )
    merged_policies = merge_clustering_policies_from_raw(
        body.failure_policies,
        job.metric_clusters,
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

    if not has_clusterable_evaluator_results(db, job, merged_policies):
        raise HTTPException(
            status_code=400,
            detail=(
                "No calls match any failure policy. Select failure values on "
                "metrics that have matching rows, or leave metrics with no "
                "failures unchecked — they are skipped automatically."
            ),
        )

    try:
        _filtered, selected_row_ids = resolve_source_row_selection(
            db,
            job,
            evaluation_row_ids=body.evaluation_row_ids,
            row_limit=body.row_limit,
            policies=merged_policies,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not selected_row_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                "No eligible rows to cluster. Select completed calls that match "
                "at least one configured failure policy."
            ),
        )

    _enqueue_cluster_job(
        db,
        job,
        provider=body.provider,
        model=body.model,
        credential_id=body.credential_id,
        force=body.force or body.regenerate,
        max_llm_calls=body.max_llm_calls,
        evaluation_row_ids=body.evaluation_row_ids,
        selected_evaluation_row_ids=selected_row_ids,
        failure_policies=merged_policies,
        row_limit=body.row_limit,
    )

    db.refresh(job)
    return metric_clusters_payload(job) or EvaluationMetricClustersState(status="running")


@router.post(
    "/cancel",
    response_model=EvaluationMetricClustersState,
    operation_id="cancelEvaluatorResultMetricClusters",
)
def cancel_evaluator_result_metric_clusters(
    scope: dict = Depends(_cluster_scope_query_params),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> EvaluationMetricClustersState:
    job = _get_job(db, organization_id, workspace_id, **scope)
    db.commit()
    if apply_metric_clusters_cancel(job):
        _revoke_cluster_task(job)
        flag_modified(job, "metric_clusters")
        db.commit()
        db.refresh(job)
    return metric_clusters_payload(job) or EvaluationMetricClustersState(status="idle")


@router.delete(
    "",
    status_code=204,
    operation_id="deleteEvaluatorResultMetricClusters",
)
def delete_evaluator_result_metric_clusters(
    scope: dict = Depends(_cluster_scope_query_params),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> None:
    if not scope.get("job_id") and not scope.get("scope_key") and not scope.get("agent_id"):
        raise HTTPException(status_code=400, detail="agent_id is required")
    job = _get_job(db, organization_id, workspace_id, **scope)
    db.commit()
    if apply_metric_clusters_cancel(job):
        _revoke_cluster_task(job)
        flag_modified(job, "metric_clusters")
        db.commit()
    delete_cluster_job(db, job)
    db.commit()
