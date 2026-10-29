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

def _require_import(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
) -> CallImport:
    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(status_code=404, detail="Call import not found")
    return call_import


def require_call_import_capability(capability: str):
    """Ensure the caller has *capability* in the call import's workspace (not just the header)."""

    def _dep(
        call_import_id: UUID,
        principal: Principal = Depends(get_principal),
        organization_id: UUID = Depends(get_organization_id),
        db: Session = Depends(get_db),
    ) -> CallImport:
        call_import = _require_import(db, call_import_id, organization_id)
        caps, _, role = resolve_workspace_capabilities(
            db,
            principal=principal,
            workspace_id=call_import.workspace_id,
            organization_id=organization_id,
        )
        if capability not in caps:
            raise HTTPException(
                status_code=403,
                detail=capability_denied_message(
                    capability,
                    role_name=role.name if role else None,
                    workspace_label="the active workspace",
                ),
            )
        return call_import

    return _dep


def _pick_evaluation_row_transcript(
    source_row: Optional[CallImportRow],
    evaluation: Optional[CallImportEvaluation] = None,
) -> Optional[str]:
    """Transcript shown in evaluation row detail for the run's source."""
    if source_row is None:
        return None
    source = (
        (evaluation.transcript_source or "diarised").strip().lower()
        if evaluation is not None
        else "diarised"
    )
    if source == "production":
        raw = (source_row.transcript or "").strip()
        return raw or None
    diarised = (source_row.diarised_transcript or "").strip()
    if diarised:
        return diarised
    raw = (source_row.transcript or "").strip()
    return raw or None


def _to_evaluation_row_response(
    eval_row_obj: CallImportEvaluationRow,
    source_row: Optional[CallImportRow],
    evaluation: Optional[CallImportEvaluation] = None,
    *,
    include_text: bool = True,
) -> CallImportEvaluationRowResponse:
    """Serialize one evaluation row plus joined source-row metadata.

    List pages pass ``include_text=False`` so transcript bodies stay off
    the page. The single-row read passes ``True``.
    """
    if include_text and source_row is not None:
        transcript = _pick_evaluation_row_transcript(source_row, evaluation)
        production_transcript = (source_row.transcript or "").strip() or None
        diarised_transcript = (source_row.diarised_transcript or "").strip() or None
        raw_columns = source_row.raw_columns
    else:
        transcript = None
        production_transcript = None
        diarised_transcript = None
        raw_columns = None
    return CallImportEvaluationRowResponse(
        id=eval_row_obj.id,
        evaluation_id=eval_row_obj.evaluation_id,
        call_import_row_id=eval_row_obj.call_import_row_id,
        row_index=source_row.row_index if source_row else None,
        conversation_id=source_row.conversation_id if source_row else None,
        transcript=transcript,
        production_transcript=production_transcript,
        diarised_transcript=diarised_transcript,
        raw_columns=raw_columns,
        recording_url=source_row.recording_url if source_row else None,
        recording_date=source_row.recording_date if source_row else None,
        recording_s3_key=source_row.recording_s3_key if source_row else None,
        diarised_transcript_status=(
            source_row.diarised_transcript_status if source_row else None
        ),
        diarised_transcript_error=(
            source_row.diarised_transcript_error if source_row else None
        ),
        status=eval_row_obj.status,
        metric_scores=eval_row_obj.metric_scores or {},
        error_message=eval_row_obj.error_message,
        started_at=eval_row_obj.started_at,
        finished_at=eval_row_obj.finished_at,
        created_at=eval_row_obj.created_at,
        updated_at=eval_row_obj.updated_at,
    )


def _serialize_selected_metric_ids(value) -> List[UUID]:
    result: List[UUID] = []
    if not isinstance(value, list):
        return result
    for item in value:
        try:
            result.append(UUID(str(item)))
        except (TypeError, ValueError):
            continue
    return result


def _metrics_for_ids(db: Session, org_id: UUID, ids: List[UUID]) -> List[Metric]:
    if not ids:
        return []
    rows = (
        db.query(Metric)
        .filter(
            Metric.organization_id == org_id,
            Metric.id.in_(ids),
        )
        .all()
    )
    by_id = {row.id: row for row in rows}
    return [by_id[mid] for mid in ids if mid in by_id]


def _expand_metric_selection(
    db: Session,
    org_id: UUID,
    selected_ids: List[UUID],
) -> Tuple[List[Metric], Dict[UUID, List[Metric]]]:
    """Resolve user-supplied metric ids into actual leaves + parent grouping.

    Rules:
      * If a parent id is in ``selected_ids`` and no specific children of
        that parent are also listed, include EVERY enabled child of that
        parent.
      * If a parent id AND some of its children are listed, include only
        the listed children (treat the parent selection as the
        "container" so users can deselect labels).
      * Standalone metrics (no parent, no children) pass through
        unchanged.
      * Disabled metrics are filtered out at this layer so the caller
        doesn't have to repeat the check.

    Returns:
        (effective_metrics, parent_to_children)

        ``effective_metrics`` is the deduplicated list of metrics the
        worker will actually score (children + standalone). Order is
        preserved from ``selected_ids`` for display stability.

        ``parent_to_children`` maps each parent metric id (UUID) to the
        list of its selected children. Useful for grouping in the LLM
        prompt builder.
    """
    if not selected_ids:
        return [], {}

    requested = list(selected_ids)
    initial_rows = (
        db.query(Metric)
        .filter(
            Metric.organization_id == org_id,
            Metric.id.in_(requested),
        )
        .all()
    )
    initial_by_id = {row.id: row for row in initial_rows}

    parent_ids_requested = {
        m.id for m in initial_rows if m.selection_mode and not m.parent_metric_id
    }
    # Map parent id -> children explicitly requested by the user.
    explicit_children_by_parent: Dict[UUID, List[Metric]] = {}
    for m in initial_rows:
        if m.parent_metric_id and m.parent_metric_id in parent_ids_requested:
            explicit_children_by_parent.setdefault(
                m.parent_metric_id, []
            ).append(m)

    # For parents without explicit children, hydrate every enabled child.
    parents_needing_full_expansion = [
        pid
        for pid in parent_ids_requested
        if pid not in explicit_children_by_parent
    ]
    auto_expanded_children: Dict[UUID, List[Metric]] = {}
    if parents_needing_full_expansion:
        for pid in parents_needing_full_expansion:
            child_rows = (
                db.query(Metric)
                .filter(
                    Metric.organization_id == org_id,
                    Metric.parent_metric_id == pid,
                    Metric.enabled.is_(True),
                )
                .order_by(Metric.created_at.asc())
                .all()
            )
            auto_expanded_children[pid] = child_rows

    parent_to_children: Dict[UUID, List[Metric]] = {}
    for pid in parent_ids_requested:
        children = explicit_children_by_parent.get(
            pid
        ) or auto_expanded_children.get(pid, [])
        # Drop disabled children so the worker doesn't waste a slot on
        # them. Empty parents (no enabled children) are still tracked
        # because the UI may want to show "0 of 0" rather than swallow
        # them silently.
        parent_to_children[pid] = [c for c in children if c.enabled]

    effective: List[Metric] = []
    seen: set[UUID] = set()
    for mid in requested:
        m = initial_by_id.get(mid)
        if m is None:
            continue
        if m.selection_mode and not m.parent_metric_id:
            # Parent row itself is not scored — only its children.
            for child in parent_to_children.get(m.id, []):
                if child.id in seen or not child.enabled:
                    continue
                seen.add(child.id)
                effective.append(child)
            continue
        if m.parent_metric_id and m.parent_metric_id in parent_ids_requested:
            # Already accounted for via the parent expansion above.
            continue
        if not m.enabled:
            continue
        if m.id in seen:
            continue
        seen.add(m.id)
        effective.append(m)

    return effective, parent_to_children


def _evaluation_bulk_operation_for_response(
    evaluation_id: UUID,
) -> Optional[str]:
    from app.services.call_imports.evaluation_bulk_op import (
        get_evaluation_bulk_operation,
    )

    return get_evaluation_bulk_operation(evaluation_id)


def _serialize_eval(
    db: Session,
    row: CallImportEvaluation,
    *,
    sibling_evaluation_ids: Optional[List[UUID]] = None,
    user_emails: Optional[Dict[UUID, str]] = None,
) -> CallImportEvaluationResponse:
    from app.api.v1.routes.call_import_evaluations.clusters import (
        _metric_clusters_payload,
    )
    from app.api.v1.routes.call_import_evaluations.insights import (
        _tldr_summary_payload,
        _user_insights_payload,
    )

    selected_ids = _serialize_selected_metric_ids(row.selected_metric_ids)

    # Pull every metric referenced anywhere in the run's grouping (leaves,
    # standalone, AND parents from selected_metric_groups) so the UI can
    # render parent labels even when only children were materialized into
    # selected_metric_ids.
    groups_raw: Dict[str, List[str]] = {}
    if isinstance(row.selected_metric_groups, dict):
        for parent_str, children in row.selected_metric_groups.items():
            if not isinstance(children, list):
                continue
            cleaned: List[str] = []
            for c in children:
                try:
                    UUID(str(c))
                    cleaned.append(str(c))
                except (TypeError, ValueError):
                    continue
            try:
                UUID(parent_str)
                groups_raw[parent_str] = cleaned
            except (TypeError, ValueError):
                continue

    metric_ids_for_lookup: List[UUID] = list(selected_ids)
    for parent_str in groups_raw.keys():
        try:
            pid = UUID(parent_str)
            if pid not in metric_ids_for_lookup:
                metric_ids_for_lookup.append(pid)
        except (TypeError, ValueError):
            continue

    metrics = _metrics_for_ids(
        db, row.organization_id, metric_ids_for_lookup
    )

    from app.services.call_imports.progress_counters import merge_eval_counters_for_ui

    ui_completed_raw, ui_failed_raw = merge_eval_counters_for_ui(row)
    total = int(row.total_rows or 0)
    ui_completed = (
        min(ui_completed_raw, total) if total else ui_completed_raw
    )
    ui_failed = min(ui_failed_raw, total) if total else ui_failed_raw

    if user_emails is None:
        user_emails = emails_for_user_ids(db, user_ids_from_evaluations([row]))
    created_email, updated_email = actor_emails_for_evaluation(row, user_emails)

    from app.workers.tasks.evaluate_call_import_row_core import (
        count_distinct_llm_configs_for_metrics,
    )

    selected_set = set(selected_ids)
    scoring_metrics = [m for m in metrics if m.id in selected_set]
    expected_llm_calls_per_row = count_distinct_llm_configs_for_metrics(
        scoring_metrics,
        overrides=(
            row.metric_llm_overrides
            if isinstance(row.metric_llm_overrides, dict)
            else {}
        ),
        run_provider=(row.llm_provider or "").strip() or None,
        run_model=(row.llm_model or "").strip() or None,
        run_llm_config=(
            row.llm_config if isinstance(getattr(row, "llm_config", None), dict) else None
        ),
        run_credential_id=(
            str(row.llm_credential_id) if row.llm_credential_id else None
        ),
    )

    return CallImportEvaluationResponse(
        id=row.id,
        call_import_id=row.call_import_id,
        organization_id=row.organization_id,
        name=row.name,
        selected_metric_ids=selected_ids,
        selected_metric_groups=groups_raw or None,
        metrics=[
            CallImportMetricSummary(
                id=metric.id,
                name=metric.name,
                metric_type=metric.metric_type,
                description=metric.description,
                parent_metric_id=metric.parent_metric_id,
                selection_mode=metric.selection_mode,
                # Required by the Flow tab to know whether a parent
                # opted into discovery; without it the
                # DiscoveredLabelsPanel stays hidden even when the
                # worker is actively producing discovered_labels.
                allow_discovery=bool(
                    getattr(metric, "allow_discovery", False)
                ),
            )
            for metric in metrics
        ],
        status=row.status,
        total_rows=row.total_rows,
        completed_rows=ui_completed,
        failed_rows=ui_failed,
        error_message=row.error_message,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        llm_credential_id=row.llm_credential_id,
        llm_config=(
            row.llm_config if isinstance(getattr(row, "llm_config", None), dict) else None
        ),
        metric_llm_overrides=(
            row.metric_llm_overrides
            if isinstance(row.metric_llm_overrides, dict)
            else None
        ),
        stt_provider=row.stt_provider,
        stt_model=row.stt_model,
        stt_credential_id=row.stt_credential_id,
        diarisation_llm_provider=getattr(row, "diarisation_llm_provider", None),
        diarisation_llm_model=getattr(row, "diarisation_llm_model", None),
        diarisation_llm_credential_id=getattr(
            row, "diarisation_llm_credential_id", None
        ),
        diarisation_prompt=getattr(row, "diarisation_prompt", None),
        transcribe_mode=(
            (getattr(row, "transcribe_mode", None) or "stt_llm")
        ),
        transcript_source=(row.transcript_source or "diarised"),
        sibling_evaluation_ids=list(sibling_evaluation_ids or []),
        expected_llm_calls_per_row=expected_llm_calls_per_row,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by_email=created_email,
        last_updated_by_email=updated_email,
        tldr_summary=_tldr_summary_payload(row),
        user_insights=_user_insights_payload(row),
        metric_clusters=_metric_clusters_payload(row),
        discover_new_metrics=bool(
            getattr(row, "discover_new_metrics", False)
        ),
        bulk_operation=_evaluation_bulk_operation_for_response(row.id),
    )


def _normalize_name(value: Optional[str]) -> Optional[str]:
    """Trim user-supplied name; empty string becomes ``NULL``."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _rollup_evaluation_status(evaluation: CallImportEvaluation, db: Session) -> None:
    """Recompute counters + terminal status after rows are added/removed.

    Uses a single aggregate query instead of loading every row status.
    """
    from app.workers.tasks.evaluate_call_import_row_core import (
        _apply_parent_status_from_counters,
        reconcile_evaluation_counters,
    )

    reconcile_evaluation_counters(db, evaluation)
    _apply_parent_status_from_counters(evaluation)
    db.flush()

    if evaluation.status in {"completed", "failed", "partial"}:
        from app.models.database import CallImport
        from app.services.call_imports.bulk_ops import rollup_call_import_batch_status

        call_import = (
            db.query(CallImport)
            .filter(CallImport.id == evaluation.call_import_id)
            .first()
        )
        if call_import is not None:
            rollup_call_import_batch_status(db, call_import)

def _load_eval_rows(db: Session, evaluation_id: UUID) -> List[CallImportEvaluationRow]:
    from app.db_sharding.scatter_gather import load_evaluation_score_rows

    return load_evaluation_score_rows(db, evaluation_id)


def _count_completed_eval_rows(db: Session, evaluation_id: UUID) -> int:
    from app.db_sharding.eval_rows import count_evaluation_rows_for_run

    return count_evaluation_rows_for_run(
        db, evaluation_id, statuses=["completed"]
    )


def _completed_row_pairs_for_evaluation(
    db: Session,
    evaluation_id: UUID,
) -> List[Tuple[CallImportEvaluationRow, CallImportRow]]:
    from app.db_sharding.scatter_gather import load_evaluation_row_pairs

    row_pairs = load_evaluation_row_pairs(db, evaluation_id)
    return [
        (eval_row, source_row)
        for eval_row, source_row in row_pairs
        if eval_row.status == "completed"
    ]
