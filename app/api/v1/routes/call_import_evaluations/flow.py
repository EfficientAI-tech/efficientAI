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
    _load_eval_rows,
    _metrics_for_ids,
    _require_import,
)
from app.api.v1.routes.call_import_evaluations.discovered import (  # noqa: E402
    _alias_map_for_parent,
    _promoted_child_slugs,
    _resolve_alias,
    _slug_label,
)

_FLOW_TERMINAL_THRESHOLD = 0.2  # Mark as terminal when >=20% of sequences end here.
_FLOW_START_NODE_ID = "__START__"
_DISCOVERED_NODE_PREFIX = "disc:"
def _build_flow_graph(
    eval_rows: List[CallImportEvaluationRow],
    parent_metric: Metric,
    children: List[Metric],
    alias_map: Optional[Dict[str, str]] = None,
    extra_children: Optional[List[Metric]] = None,
) -> MetricFlowResponse:
    """Walk per-row ``sequence`` arrays and produce aggregate nodes/edges.

    A synthetic ``START`` node is prepended to every sequence so the
    diagram has a single origin. Children that never appear in any
    sequence are still emitted as nodes (count=0) so the UI can render
    them in the legend.

    ``alias_map`` lets callers fold merged-out discovered slugs into
    their canonical target before building the graph; ``extra_children``
    are children of the parent that aren't in the legend list (e.g.
    children promoted *after* the evaluation was created and therefore
    missing from ``selected_metric_groups``) but should still resolve in
    sequences so the slug doesn't get redrawn as a discovered candidate.
    """
    parent_id_str = str(parent_metric.id)
    aliases = alias_map or {}
    # Build a fast lookup keyed by both the lower_snake child key (what the
    # LLM emits in ``sequence``) and the child UUID (what some clients may
    # store) so legacy / drifted payloads still resolve.
    child_lookup: Dict[str, Metric] = {}
    for child in children:
        slug = _slug_label(child.name)
        child_lookup[slug] = child
        child_lookup[str(child.id)] = child
    # ``extra_children`` are resolved-only — they shouldn't add legend
    # nodes (those come from the explicit ``children`` argument), but
    # they need to be in ``child_lookup`` so a sequence step that
    # matches a freshly-promoted child resolves to the real child UUID
    # instead of falling through to ``discovered_lookup`` and rendering
    # as a "discovered" node.
    if extra_children:
        for child in extra_children:
            slug = _slug_label(child.name)
            if slug and slug not in child_lookup:
                child_lookup[slug] = child
            cid = str(child.id)
            child_lookup.setdefault(cid, child)

    # Discovered labels: walk every row's discovered_labels first so we
    # know which discovered slugs are valid before resolving sequences.
    # Discovered nodes get a ``disc:`` prefixed id so they can't collide
    # with real child UUIDs in the node/edge graph. We apply
    # ``alias_map`` first so merged-out source slugs fold into their
    # canonical target — preserving the user's "merge" intent on still-
    # in-flight rows whose JSON wasn't rewritten by the merge endpoint.
    discovered_lookup: Dict[str, Dict[str, Any]] = {}
    for row in eval_rows:
        scores = (
            row.metric_scores if isinstance(row.metric_scores, dict) else {}
        )
        parent_entry = scores.get(parent_id_str)
        if not isinstance(parent_entry, dict):
            continue
        raw_discovered = parent_entry.get("discovered_labels")
        if not isinstance(raw_discovered, list):
            continue
        for entry in raw_discovered:
            if not isinstance(entry, dict):
                continue
            slug = _slug_label(entry.get("key") or entry.get("name"))
            slug = _resolve_alias(aliases, slug)
            if not slug or slug in child_lookup:
                continue
            name = (entry.get("name") or "").strip() or slug.replace("_", " ")
            existing = discovered_lookup.get(slug)
            if existing is None:
                discovered_lookup[slug] = {
                    "id": f"{_DISCOVERED_NODE_PREFIX}{slug}",
                    "name": name,
                }

    node_counts: Dict[str, int] = {}
    edge_counts: Dict[tuple[str, str], int] = {}
    terminal_counts: Dict[str, int] = {}

    total_rows = len(eval_rows)
    rows_with_sequence = 0

    for row in eval_rows:
        scores = (
            row.metric_scores if isinstance(row.metric_scores, dict) else {}
        )
        parent_entry = scores.get(parent_id_str)
        if not isinstance(parent_entry, dict):
            continue
        raw_sequence = parent_entry.get("sequence")
        if not isinstance(raw_sequence, list):
            continue

        resolved_ids: List[str] = []
        last_resolved: Optional[str] = None
        for item in raw_sequence:
            if not isinstance(item, str):
                continue
            normalized = _resolve_alias(aliases, _slug_label(item))
            child = child_lookup.get(normalized) or child_lookup.get(item)
            if child is not None:
                cid = str(child.id)
                # Adjacent dedupe AFTER alias resolution so two
                # different raw slugs that fold to the same target
                # don't draw a self-edge through the chart.
                if cid == last_resolved:
                    continue
                resolved_ids.append(cid)
                last_resolved = cid
                continue
            disc = discovered_lookup.get(normalized)
            if disc is not None:
                if disc["id"] == last_resolved:
                    continue
                resolved_ids.append(disc["id"])
                last_resolved = disc["id"]

        if not resolved_ids:
            continue

        rows_with_sequence += 1
        for nid in resolved_ids:
            node_counts[nid] = node_counts.get(nid, 0) + 1

        edge_counts[(_FLOW_START_NODE_ID, resolved_ids[0])] = (
            edge_counts.get((_FLOW_START_NODE_ID, resolved_ids[0]), 0) + 1
        )
        for src, tgt in zip(resolved_ids, resolved_ids[1:]):
            if src == tgt:
                continue
            edge_counts[(src, tgt)] = edge_counts.get((src, tgt), 0) + 1

        terminal_id = resolved_ids[-1]
        terminal_counts[terminal_id] = terminal_counts.get(terminal_id, 0) + 1

    nodes: List[MetricFlowNode] = []
    # Always include a START node so the UI has a stable entry point.
    nodes.append(
        MetricFlowNode(
            id=_FLOW_START_NODE_ID,
            label="Start",
            count=rows_with_sequence,
            is_terminal=False,
        )
    )

    def _emit_child_node(child: Metric) -> None:
        cid = str(child.id)
        count = node_counts.get(cid, 0)
        terminal_count = terminal_counts.get(cid, 0)
        is_terminal = False
        if rows_with_sequence > 0:
            is_terminal = (
                terminal_count / rows_with_sequence
            ) >= _FLOW_TERMINAL_THRESHOLD
        nodes.append(
            MetricFlowNode(
                id=cid,
                label=child.name,
                count=count,
                is_terminal=is_terminal,
            )
        )

    emitted_child_ids: set[str] = set()
    for child in children:
        cid = str(child.id)
        if cid in emitted_child_ids:
            continue
        emitted_child_ids.add(cid)
        _emit_child_node(child)
    # Extra children (promoted after the eval was created) only get
    # legend nodes if they actually appear in the data — otherwise we'd
    # pollute the diagram with every standalone promotion the user has
    # ever made under this parent.
    if extra_children:
        for child in extra_children:
            cid = str(child.id)
            if cid in emitted_child_ids:
                continue
            if node_counts.get(cid, 0) == 0:
                continue
            emitted_child_ids.add(cid)
            _emit_child_node(child)
    # Append discovered nodes after the real children so legend ordering
    # keeps user-defined labels first.
    for slug, info in discovered_lookup.items():
        nid = info["id"]
        count = node_counts.get(nid, 0)
        terminal_count = terminal_counts.get(nid, 0)
        is_terminal = False
        if rows_with_sequence > 0:
            is_terminal = (
                terminal_count / rows_with_sequence
            ) >= _FLOW_TERMINAL_THRESHOLD
        nodes.append(
            MetricFlowNode(
                id=nid,
                label=info["name"],
                count=count,
                is_terminal=is_terminal,
                is_discovered=True,
            )
        )

    edges: List[MetricFlowEdge] = [
        MetricFlowEdge(source=src, target=tgt, count=count)
        for (src, tgt), count in sorted(
            edge_counts.items(), key=lambda kv: kv[1], reverse=True
        )
    ]

    return MetricFlowResponse(
        parent_metric_id=parent_id_str,
        parent_metric_name=parent_metric.name,
        selection_mode=parent_metric.selection_mode,
        nodes=nodes,
        edges=edges,
        total_rows=total_rows,
        rows_with_sequence=rows_with_sequence,
    )


@router.get(
    "/{eval_id}/flow",
    response_model=MetricFlowResponse,
    operation_id="getCallImportEvaluationFlow",
)
async def get_call_import_evaluation_flow(
    call_import_id: UUID,
    eval_id: UUID,
    parent_metric_id: UUID = Query(
        ...,
        description=(
            "Parent (category) metric whose children's sequences should be "
            "aggregated into a flow graph."
        ),
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> MetricFlowResponse:
    """Aggregate the LLM-inferred per-row sequences into one flow graph.

    Returns ``nodes`` (one per child of the parent metric, plus a
    synthetic ``START`` node) and ``edges`` (counts of consecutive
    label transitions across every row that produced a sequence). The
    frontend feeds this directly into a React Flow / xyflow canvas;
    edge thickness should scale with ``count / total_rows`` and
    ``is_terminal`` nodes should be styled as outcomes.
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

    parent = (
        db.query(Metric)
        .filter(
            Metric.id == parent_metric_id,
            Metric.organization_id == organization_id,
        )
        .first()
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail="Parent metric not found in this organization.",
        )
    if not parent.selection_mode:
        raise HTTPException(
            status_code=400,
            detail=(
                "Flow charts are only meaningful for parent metrics "
                "(selection_mode set). This metric is standalone."
            ),
        )

    # Children are taken from selected_metric_groups when present so the
    # flow chart reflects exactly the subset that ran in this
    # evaluation; otherwise fall back to every enabled child of the
    # parent.
    groups_raw = (
        evaluation.selected_metric_groups
        if isinstance(evaluation.selected_metric_groups, dict)
        else {}
    )
    parent_id_str = str(parent.id)
    children: List[Metric] = []
    if parent_id_str in groups_raw and isinstance(
        groups_raw[parent_id_str], list
    ):
        child_ids: List[UUID] = []
        for c in groups_raw[parent_id_str]:
            try:
                child_ids.append(UUID(str(c)))
            except (TypeError, ValueError):
                continue
        if child_ids:
            children = (
                db.query(Metric)
                .filter(
                    Metric.organization_id == organization_id,
                    Metric.id.in_(child_ids),
                )
                .order_by(Metric.created_at.asc())
                .all()
            )
    if not children:
        children = (
            db.query(Metric)
            .filter(
                Metric.organization_id == organization_id,
                Metric.parent_metric_id == parent.id,
            )
            .order_by(Metric.created_at.asc())
            .all()
        )

    # Children promoted AFTER this evaluation was created aren't in
    # ``selected_metric_groups`` but their slugs still appear in already-
    # scored rows' sequences. Pass them as ``extra_children`` so those
    # sequence entries resolve against the real (now promoted) child
    # instead of being redrawn as discovered candidates.
    extra_children: List[Metric] = []
    if children:
        existing_ids = {child.id for child in children}
        all_children = (
            db.query(Metric)
            .filter(
                Metric.organization_id == organization_id,
                Metric.parent_metric_id == parent.id,
            )
            .all()
        )
        extra_children = [c for c in all_children if c.id not in existing_ids]

    eval_rows = _load_eval_rows(db, eval_id)

    alias_map = _alias_map_for_parent(evaluation, parent.id)
    return _build_flow_graph(
        eval_rows,
        parent,
        children,
        alias_map=alias_map,
        extra_children=extra_children,
    )
