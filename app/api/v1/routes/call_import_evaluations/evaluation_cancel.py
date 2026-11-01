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
    _rollup_evaluation_status,
    _to_evaluation_row_response,
)
def _revoke_pending_tasks(evaluation: CallImportEvaluation) -> None:
    """Best-effort cancel of any in-flight Celery tasks for an evaluation."""

    if not evaluation.celery_group_id and not any(
        r.celery_task_id for r in evaluation.row_results
    ):
        return
    try:
        from app.workers.celery_app import celery_app

        pending_task_ids = [
            eval_row.celery_task_id
            for eval_row in evaluation.row_results
            if eval_row.celery_task_id
            and eval_row.status in {"pending", "running"}
        ]
        if pending_task_ids:
            celery_app.control.revoke(pending_task_ids, terminate=False)
    except Exception:
        # Best effort — DB delete remains the source of truth.
        pass


# ---------------------------------------------------------------------------
# User-initiated cancel for in-flight evaluation rows
# ---------------------------------------------------------------------------
#
# Evaluation rows can sit in ``running`` for many minutes when the underlying
# LLM / audio metric call is slow or wedged (the worker carries an 8 min
# soft / 10 min hard time limit). Without a cancel affordance the operator's
# only recourse is to wait for Celery's time limit to fire — or to manually
# mutate the DB. These helpers + the two endpoints below give the UI a
# first-class "Abort" button mirroring the diarisation cancel pattern at
# ``app.api.v1.routes.call_imports`` (``_apply_diarisation_cancel`` etc.).
#
# Revoke uses :mod:`app.workers.celery_revoke` — ``terminate`` is off by default
# because ``worker-imports`` runs ``--pool=threads`` (Celery cannot kill threads).
# Rows are marked cancelled in the DB first; eval workers cooperatively exit via
# ``was_cancelled_externally``. Set ``celery.revoke_use_terminate: true`` only
# when every targeted worker uses prefork and you need SIGTERM mid-flight.

# Sentinel error message stamped on cancelled rows. Read by the eval worker's
# ``_was_cancelled_externally`` guard (see
# :mod:`app.workers.tasks.evaluate_call_import_row`) so a worker that's already
# past its slowest operation can't overwrite the cancelled state with its own
# terminal status. Touching either copy means touching both.
EVAL_CANCELLED_BY_USER_ERROR: str = "Evaluation cancelled by user"


def _cancellable_eval_states() -> Tuple[str, ...]:
    """States that an evaluation row can be cancelled from.

    Kept as a tiny helper so adding a future ``"queued"`` / ``"retrying"``
    state only needs one edit.
    """
    return ("pending", "running")


def _revoke_eval_task(eval_row: CallImportEvaluationRow) -> None:
    """Best-effort revoke of a single eval row's Celery task.

    Always swallows control-plane exceptions — Celery's control bus is
    inherently best-effort and a missed revoke is not catastrophic
    because the DB row is already flipped to ``failed`` by the caller
    before this runs (so the UI immediately reflects the cancel; if
    the task happens to finish anyway, the worker's finaliser skips
    over the row via :data:`EVAL_CANCELLED_BY_USER_ERROR`).
    """
    task_id = (eval_row.celery_task_id or "").strip()
    if not task_id:
        return
    from app.workers.celery_revoke import revoke_celery_tasks

    if revoke_celery_tasks([task_id]):
        logger.info(
            "Revoked evaluation task {} for eval row {}",
            task_id,
            eval_row.id,
        )


def _cancel_eval_row_with_source_diarisation(
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow | None,
    *,
    cascade_diarisation: bool,
    now: datetime | None = None,
) -> list[str]:
    """Mark an eval row cancelled; optionally fail in-flight diarisation.

    Returns Celery task ids to revoke (deduped). The caller may batch-revoke
    them; when ``cascade_diarisation`` is true, diarisation revoke also runs
    inside :func:`_apply_diarisation_cancel` for the source row's task id.
    """
    cancellable_states = _cancellable_eval_states()
    if (eval_row.status or "").lower() not in cancellable_states:
        return []

    stamp = now or datetime.now(timezone.utc)
    task_ids: list[str] = []
    eval_task_id = (eval_row.celery_task_id or "").strip()
    if eval_task_id:
        task_ids.append(eval_task_id)

    eval_row.status = "failed"
    eval_row.error_message = EVAL_CANCELLED_BY_USER_ERROR
    eval_row.finished_at = stamp
    eval_row.celery_task_id = None

    if cascade_diarisation and source_row is not None:
        from app.api.v1.routes.call_imports import _apply_diarisation_cancel

        source_task_id = (source_row.celery_task_id or "").strip()
        if source_task_id and source_task_id not in task_ids:
            task_ids.append(source_task_id)
        _apply_diarisation_cancel([source_row])

    return list(dict.fromkeys(task_ids))


def _apply_evaluation_cancel(
    eval_rows: List[CallImportEvaluationRow],
    *,
    source_rows: dict[UUID, CallImportRow] | None = None,
    cascade_diarisation: bool = False,
) -> Tuple[int, int]:
    """Cancel every cancellable row in ``eval_rows``.

    Returns ``(cancelled, skipped)`` so the caller can build a typed
    response without re-querying the DB. The caller is responsible for
    ``db.commit()`` after this returns — we deliberately don't commit
    here so a batch endpoint can flush all rows in one transaction.
    """
    cancellable_states = _cancellable_eval_states()
    cancelled = 0
    skipped = 0
    now = datetime.now(timezone.utc)
    source_rows = source_rows or {}
    for eval_row in eval_rows:
        if (eval_row.status or "").lower() not in cancellable_states:
            skipped += 1
            continue
        source_row = source_rows.get(eval_row.call_import_row_id)
        task_ids = _cancel_eval_row_with_source_diarisation(
            eval_row,
            source_row,
            cascade_diarisation=cascade_diarisation,
            now=now,
        )
        for task_id in task_ids:
            _revoke_eval_task_by_id(task_id, eval_row_id=eval_row.id)
        cancelled += 1
    return cancelled, skipped


def _revoke_eval_task_by_id(task_id: str, *, eval_row_id: UUID) -> None:
    """Best-effort revoke when the task id is known outside the ORM row."""
    cleaned = (task_id or "").strip()
    if not cleaned:
        return
    from app.workers.celery_revoke import revoke_celery_tasks

    if revoke_celery_tasks([cleaned]):
        logger.info(
            "Revoked evaluation task {} for eval row {}",
            cleaned,
            eval_row_id,
        )


def _claim_evaluation_bulk_operation(
    evaluation_id: UUID,
    operation: str,
) -> None:
    """Reserve the run for a single bulk worker pass; 409 if one is active."""
    from app.services.call_imports.evaluation_bulk_op import (
        get_evaluation_bulk_operation,
        try_set_evaluation_bulk_operation,
    )

    if try_set_evaluation_bulk_operation(evaluation_id, operation):  # type: ignore[arg-type]
        return
    existing = get_evaluation_bulk_operation(evaluation_id) or operation
    raise HTTPException(
        status_code=409,
        detail=(
            f"A bulk {existing.replace('_', ' ')} operation is already in "
            "progress for this evaluation. Wait for it to finish before "
            "starting another action."
        ),
    )


def _require_no_evaluation_bulk_operation(evaluation_id: UUID) -> None:
    from app.services.call_imports.evaluation_bulk_op import (
        get_evaluation_bulk_operation,
    )

    existing = get_evaluation_bulk_operation(evaluation_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A bulk {existing.replace('_', ' ')} operation is already in "
                "progress for this evaluation. Wait for it to finish before "
                "starting another action."
            ),
        )


@router.post(
    "/{eval_id}/cancel",
    response_model=CallImportEvaluationBulkActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="cancelCallImportEvaluation",
)
async def cancel_call_import_evaluation(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportEvaluationBulkActionResponse:
    """Abort all in-flight (or queued) rows in a single evaluation run.

    Idempotent: calling on a run whose rows are already terminal returns
    ``target_count=0`` with 202 so the UI can fire this from an
    "Abort" button without having to pre-check the state.

    Heavy row resets and Celery revokes run in a background worker so
    large batches do not block the API thread.
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

    from app.services.call_imports.bulk_ops import count_evaluation_cancel_targets

    target_count = count_evaluation_cancel_targets(db, eval_id, mode="abort")
    if target_count == 0:
        from app.services.call_imports.bulk_ops import (
            count_inflight_diarisation_for_evaluation,
        )

        inflight_diarisation = count_inflight_diarisation_for_evaluation(
            db,
            eval_id,
            evaluation.call_import_id,
        )
        if inflight_diarisation == 0:
            return CallImportEvaluationBulkActionResponse(
                accepted=True,
                target_count=0,
                worker_enqueued=False,
                evaluation_id=eval_id,
            )
        _claim_evaluation_bulk_operation(eval_id, "abort")
        from app.workers.tasks.call_import_bulk_ops import (
            cancel_call_import_evaluation_task,
        )

        cancel_call_import_evaluation_task.delay(str(eval_id), mode="abort")
        return CallImportEvaluationBulkActionResponse(
            accepted=True,
            target_count=0,
            worker_enqueued=True,
            evaluation_id=eval_id,
        )

    _claim_evaluation_bulk_operation(eval_id, "abort")
    evaluation.status = "cancelled"
    stamp_evaluation_actor(evaluation, principal)
    db.commit()

    from app.workers.tasks.call_import_bulk_ops import (
        cancel_call_import_evaluation_task,
    )

    cancel_call_import_evaluation_task.delay(str(eval_id), mode="abort")
    return CallImportEvaluationBulkActionResponse(
        accepted=True,
        target_count=target_count,
        worker_enqueued=True,
        evaluation_id=eval_id,
    )


@router.post(
    "/{eval_id}/force-fail-pending",
    response_model=CallImportEvaluationBulkActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="forceFailCallImportEvaluationPending",
)
async def force_fail_pending_call_import_evaluation_rows(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportEvaluationBulkActionResponse:
    """Force-fail only rows currently in ``pending`` for a single run.

    This is narrower than :func:`cancel_call_import_evaluation`: it leaves
    ``running`` rows untouched so operators can clear permanently queued rows
    without interrupting in-flight evaluations.

    Row updates run in a background worker so large batches do not block
    the API thread.
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

    from app.services.call_imports.bulk_ops import count_evaluation_cancel_targets

    target_count = count_evaluation_cancel_targets(
        db, eval_id, mode="force_fail_pending"
    )
    if target_count == 0:
        return CallImportEvaluationBulkActionResponse(
            accepted=True,
            target_count=0,
            worker_enqueued=False,
            evaluation_id=eval_id,
        )

    _claim_evaluation_bulk_operation(eval_id, "force_fail_pending")
    stamp_evaluation_actor(evaluation, principal)
    db.commit()

    from app.workers.tasks.call_import_bulk_ops import (
        cancel_call_import_evaluation_task,
    )

    cancel_call_import_evaluation_task.delay(
        str(eval_id), mode="force_fail_pending"
    )
    return CallImportEvaluationBulkActionResponse(
        accepted=True,
        target_count=target_count,
        worker_enqueued=True,
        evaluation_id=eval_id,
    )


@router.post(
    "/{eval_id}/rows/{eval_row_id}/cancel",
    response_model=CallImportEvaluationRowResponse,
    status_code=status.HTTP_200_OK,
    operation_id="cancelCallImportEvaluationRow",
)
async def cancel_call_import_evaluation_row(
    call_import_id: UUID,
    eval_id: UUID,
    eval_row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportEvaluationRowResponse:
    """Abort an in-flight (or queued) evaluation for a single row.

    Idempotent: calling on a row that's already terminal (``completed``
    / ``failed``) returns the row unchanged with a 200 so the UI can
    wire this to a "Stop" button without having to pre-check the
    state. Updates the parent run's rollup so its counters reflect
    the cancel immediately.
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

    _require_no_evaluation_bulk_operation(eval_id)

    from app.db_sharding.eval_rows import evaluation_row_session
    from app.db_sharding.sessions import is_sharding_enabled

    if is_sharding_enabled():
        try:
            with evaluation_row_session(eval_row_id) as (
                row_db,
                _catalog_db,
                eval_row,
                source_row,
                _shard_id,
            ):
                if eval_row.evaluation_id != eval_id:
                    raise HTTPException(
                        status_code=404,
                        detail="Evaluation row not found in this run",
                    )
                _apply_evaluation_cancel(
                    [eval_row],
                    source_rows={source_row.id: source_row},
                    cascade_diarisation=True,
                )
                row_db.commit()
                _rollup_evaluation_status(evaluation, db)
                stamp_evaluation_actor(evaluation, principal)
                db.commit()
                row_db.refresh(eval_row)
                return _to_evaluation_row_response(eval_row, source_row, evaluation)
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="Evaluation row not found in this run"
            ) from exc

    eval_row = (
        db.query(CallImportEvaluationRow)
        .filter(
            CallImportEvaluationRow.id == eval_row_id,
            CallImportEvaluationRow.evaluation_id == eval_id,
        )
        .first()
    )
    if not eval_row:
        raise HTTPException(
            status_code=404, detail="Evaluation row not found in this run"
        )

    source_row = (
        db.query(CallImportRow)
        .filter(CallImportRow.id == eval_row.call_import_row_id)
        .first()
    )
    source_rows = (
        {source_row.id: source_row} if source_row is not None else None
    )
    _apply_evaluation_cancel(
        [eval_row],
        source_rows=source_rows,
        cascade_diarisation=True,
    )
    db.flush()
    _rollup_evaluation_status(evaluation, db)
    stamp_evaluation_actor(evaluation, principal)
    db.commit()
    db.refresh(eval_row)

    return _to_evaluation_row_response(eval_row, source_row, evaluation)


@router.delete(
    "/{eval_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCallImportEvaluation",
)
async def delete_call_import_evaluation(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    del api_key
    _require_import(db, call_import_id, organization_id)

    row = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Call import evaluation not found")

    _revoke_pending_tasks(row)

    from app.services.call_imports.discovered_running_cache import (
        clear_discovered_running_cache,
    )

    clear_discovered_running_cache(eval_id)
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/bulk-delete",
    status_code=status.HTTP_200_OK,
    operation_id="bulkDeleteCallImportEvaluations",
)
async def bulk_delete_call_import_evaluations(
    call_import_id: UUID,
    payload: CallImportEvaluationBulkDelete,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Dict[str, int]:
    """Delete multiple evaluation runs scoped to one call import.

    Mirrors :func:`delete_call_import_evaluation` but in bulk so the UI
    can clear out a multi-select. Unknown ids (already deleted, or
    belonging to a different org/import) are silently skipped — the
    response just reports how many actually went away.
    """

    del api_key
    _require_import(db, call_import_id, organization_id)

    if not payload.evaluation_ids:
        return {"deleted": 0}

    rows = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id.in_(payload.evaluation_ids),
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .all()
    )
    deleted = 0
    for row in rows:
        _revoke_pending_tasks(row)
        db.delete(row)
        deleted += 1
    db.commit()
    return {"deleted": deleted}

