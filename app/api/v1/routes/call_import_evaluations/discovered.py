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

def _slug_label(value: Any) -> str:
    """Lowercase + whitespace-collapse + underscore-join.

    Used everywhere we need a stable key for a metric/label name —
    matching the same convention the worker uses when emitting
    ``sequence`` entries and discovered keys.
    """
    if value is None:
        return ""
    return "_".join(str(value).strip().lower().split())


def _resolve_alias(alias_map: Dict[str, str], key: str) -> str:
    """Walk the alias map until we hit a slug that doesn't redirect.

    The merge endpoint stores ``from_slug -> to_slug`` pairs. The delete
    endpoint stores ``from_slug -> ""`` (empty string sentinel) to mark
    a slug as tombstoned. Chains can accumulate when the user merges
    A→B and later merges B→C; this helper collapses them so callers
    always land on the final canonical slug.

    Returns:
      * the canonical slug if it still resolves to a real label,
      * an empty string if the slug has been tombstoned (callers MUST
        treat an empty result as "drop this entry entirely"),
      * the input ``key`` if it isn't aliased.

    Cycles are guarded by a hard step limit since the alias map is
    user-driven.
    """
    if not key:
        return ""
    if not alias_map:
        return key
    current = key
    seen: set[str] = set()
    for _ in range(16):
        if current in seen:
            return current
        seen.add(current)
        if current not in alias_map:
            return current
        nxt = alias_map[current]
        if nxt == current:
            return current
        if nxt == "":
            # Deletion sentinel — the user has explicitly retired this
            # slug. Propagate the empty string up so callers drop it.
            return ""
        current = nxt
    return current


# Reserved JSON key under which the worker stores top-level metric
# discoveries on each row's ``metric_scores`` dict. Mirrors the constant
# in ``app/workers/tasks/helpers/llm_evaluation.py`` — kept local here to
# avoid a worker import cycle from the routes module.
DISCOVERED_METRICS_KEY = "__discovered_metrics__"
METRIC_SCORES_META_KEYS = frozenset({DISCOVERED_METRICS_KEY, "_billing"})


def _is_metric_scores_meta_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    if not normalized:
        return True
    if normalized in {item.lower() for item in METRIC_SCORES_META_KEYS}:
        return True
    return normalized.endswith("__discovered")

# Allowed values for an LLM-suggested top-level metric type. Kept in
# sync with ``DiscoveredMetricSuggestedType`` in
# ``app/models/schemas.py``.
_DISCOVERED_METRIC_TYPES = ("boolean", "rating", "category")


def normalize_scores_with_aliases(
    metric_scores: Dict[str, Any],
    evaluation: CallImportEvaluation,
    db: Session,
    organization_id: UUID,
) -> Dict[str, Any]:
    """Rewrite per-row ``metric_scores`` to honor merges + promotions.

    Called by the worker right after ``evaluate_with_llm`` returns so
    every row that finishes AFTER a user has merged or promoted a
    discovered label persists data already reflecting that decision.
    Without this hook, a worker holding a stale prompt could re-emit a
    ``from_key`` slug long after the user merged it away.

    For every parent entry (``selection_mode != null`` and a
    ``discovered_labels`` / ``sequence`` field) we:

      * resolve discovered slugs through the evaluation's
        ``discovered_label_aliases`` map (transitively),
      * drop any discovered_labels entry whose canonical slug now
        matches a real promoted child of the parent (merging them out
        of the panel for free), and
      * collapse adjacent duplicate sequence entries that result.

    Returns ``metric_scores`` (mutated in place) for chaining.
    """
    if not isinstance(metric_scores, dict):
        return metric_scores

    aliases_top = (
        evaluation.discovered_label_aliases
        if isinstance(evaluation.discovered_label_aliases, dict)
        else {}
    )

    # Identify the parent entries inside metric_scores. They're the
    # dicts that carry a ``selection_mode`` key (set by the LLM
    # hierarchy parser) and either a ``sequence`` or a
    # ``discovered_labels`` list.
    for key, entry in list(metric_scores.items()):
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "category" and not entry.get("selection_mode"):
            continue
        try:
            parent_uuid = UUID(str(key))
        except (TypeError, ValueError):
            continue

        alias_map = {}
        sub = aliases_top.get(str(parent_uuid))
        if isinstance(sub, dict):
            alias_map = {
                str(k): str(v)
                for k, v in sub.items()
                if isinstance(k, str) and isinstance(v, str)
            }
        promoted = _promoted_child_slugs(db, parent_uuid, organization_id)

        # Rewrite discovered_labels: alias-resolve keys, drop duplicates
        # post-resolution, and drop entries that have been promoted.
        discovered = entry.get("discovered_labels")
        if isinstance(discovered, list):
            kept_disc: List[Dict[str, Any]] = []
            seen: set[str] = set()
            for d in discovered:
                if not isinstance(d, dict):
                    continue
                slug = _slug_label(d.get("key") or d.get("name"))
                slug = _resolve_alias(alias_map, slug)
                if not slug or slug in promoted or slug in seen:
                    continue
                seen.add(slug)
                new_entry = dict(d)
                new_entry["key"] = slug
                kept_disc.append(new_entry)
            entry["discovered_labels"] = kept_disc

        # Rewrite sequence: alias-resolve every entry; collapse adjacent
        # duplicates that result. We DON'T drop slugs that match
        # promoted children — the promoted child slug is still a valid
        # sequence entry; the flow chart will resolve it to the real
        # child node.
        seq = entry.get("sequence")
        if isinstance(seq, list):
            new_seq: List[str] = []
            last: Optional[str] = None
            for item in seq:
                if not isinstance(item, str):
                    continue
                slug = _resolve_alias(alias_map, _slug_label(item))
                if not slug or slug == last:
                    continue
                new_seq.append(slug)
                last = slug
            entry["sequence"] = new_seq

    # Top-level metric discoveries live alongside the parent entries
    # under the reserved ``DISCOVERED_METRICS_KEY`` slot. Apply the
    # flat evaluation-level alias/tombstone map + suppress slugs that
    # already correspond to a real top-level Metric so workers that
    # finish AFTER the user has merged / deleted / promoted can't
    # resurrect a retired candidate.
    discovered_metrics_payload = metric_scores.get(DISCOVERED_METRICS_KEY)
    if isinstance(discovered_metrics_payload, list):
        flat_alias_map = (
            evaluation.discovered_metric_aliases
            if isinstance(evaluation.discovered_metric_aliases, dict)
            else {}
        )
        promoted_metric_slugs = _promoted_top_level_metric_slugs(
            db, organization_id
        )
        kept_metrics: List[Dict[str, Any]] = []
        seen_metrics: set[str] = set()
        for d in discovered_metrics_payload:
            if not isinstance(d, dict):
                continue
            slug = _slug_label(d.get("key") or d.get("name"))
            slug = _resolve_alias(flat_alias_map, slug)
            if (
                not slug
                or slug in promoted_metric_slugs
                or slug in seen_metrics
            ):
                continue
            seen_metrics.add(slug)
            new_entry = dict(d)
            new_entry["key"] = slug
            kept_metrics.append(new_entry)
        if kept_metrics:
            metric_scores[DISCOVERED_METRICS_KEY] = kept_metrics
        else:
            # No survivors — drop the empty array so empty-discovery rows
            # keep their pre-feature payload shape.
            metric_scores.pop(DISCOVERED_METRICS_KEY, None)

    return metric_scores


def _alias_map_for_parent(
    evaluation: CallImportEvaluation, parent_metric_id: UUID
) -> Dict[str, str]:
    """Pull ``{from_slug: to_slug}`` for one parent out of the eval's blob.

    Stored shape on the evaluation row is
    ``{parent_id_str: {from_slug: to_slug, ...}}``. Returns an empty
    dict for parents that have never had a merge applied.
    """
    raw = getattr(evaluation, "discovered_label_aliases", None)
    if not isinstance(raw, dict):
        return {}
    submap = raw.get(str(parent_metric_id))
    if not isinstance(submap, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in submap.items()
        if isinstance(k, str) and isinstance(v, str)
    }


def _promoted_child_slugs(
    db: Session, parent_metric_id: UUID, organization_id: UUID
) -> set[str]:
    """Slugs of every real child currently sitting under the parent.

    The Discovered Labels panel hides any candidate whose slug already
    matches a real child — that covers both freshly-promoted candidates
    and legacy children the LLM happened to re-discover. We pull from
    the live ``metrics`` table rather than the eval's
    ``selected_metric_groups`` snapshot so newly-promoted children take
    effect immediately, even on evaluations that ran before the
    promotion.
    """
    children = (
        db.query(Metric.name)
        .filter(
            Metric.parent_metric_id == parent_metric_id,
            Metric.organization_id == organization_id,
        )
        .all()
    )
    out: set[str] = set()
    for (name,) in children:
        slug = _slug_label(name)
        if slug:
            out.add(slug)
    return out


def _promoted_top_level_metric_slugs(
    db: Session, organization_id: UUID
) -> set[str]:
    """Slugs of every top-level (non-child) Metric in the organization.

    Used to suppress discovered-metric candidates whose slug already
    matches a real standalone metric. We intentionally include both
    standalone metrics AND parent category metrics — a top-level
    discovery that collides with either name is a duplicate by
    definition.
    """
    rows = (
        db.query(Metric.name)
        .filter(
            Metric.organization_id == organization_id,
            Metric.parent_metric_id.is_(None),
        )
        .all()
    )
    out: set[str] = set()
    for (name,) in rows:
        slug = _slug_label(name)
        if slug:
            out.add(slug)
    return out


def _get_running_discovered_labels(
    db: Session,
    eval_id: UUID,
    parent_metric_id: UUID,
    organization_id: Optional[UUID] = None,
    alias_map: Optional[Dict[str, str]] = None,
    *,
    from_cache: bool = False,
) -> List[Dict[str, Any]]:
    """Slug-deduped view of every discovered label seen in this eval so far.

    Walks each ``call_import_evaluation_rows`` row's
    ``metric_scores[parent_id]["discovered_labels"]`` and folds entries
    that share the same slug. Returns a list ordered by descending
    count and stable on label key, shaped like::

        [{"key": "customer_on_hold", "name": "Customer put on hold",
          "description": "...", "sample_rationale": "...", "count": 12}]

    Powers two callers:
      * The worker prompt builder ("REUSE the existing key if it fits")
        — invoked just before each row's LLM call to feed the model the
        running list of previously-discovered labels in this evaluation.
      * The ``/discovered-labels`` API surface used by the frontend
        Discovered Labels panel to render candidates with counts +
        sample rationales.

    Non-completed rows are skipped: an in-flight row's discoveries are
    not yet reliable (the row could fail and never produce final
    metric_scores). We accept the tradeoff that rows running
    concurrently won't see each other's labels — slug-collision dedup
    catches identical re-inventions, and near-paraphrases surface in
    the UI panel where the user can manually merge.
    """

    parent_id_str = str(parent_metric_id)
    aliases = alias_map or {}
    if from_cache:
        promoted_slugs: set[str] = set()
        if organization_id is not None:
            promoted_slugs = _promoted_child_slugs(
                db, parent_metric_id, organization_id
            )
        from app.services.call_imports.discovered_running_cache import (
            load_running_label_entries,
            project_discovered_entries,
        )

        return project_discovered_entries(
            load_running_label_entries(db, eval_id, parent_metric_id),
            resolve_key=lambda raw: _resolve_alias(aliases, _slug_label(raw)),
            promoted_slugs=promoted_slugs,
        )

    from app.db_sharding.eval_rows import load_evaluation_rows_for_run

    eval_rows = load_evaluation_rows_for_run(db, eval_id)
    rows = [
        (row.metric_scores,)
        for row in eval_rows
        if row.status == CallImportRowStatus.COMPLETED.value
    ]

    # Suppress slugs that have either:
    #  * been promoted to a real child of the parent (so the panel doesn't
    #    keep nagging the user about a candidate they've already
    #    accepted), or
    #  * been merged INTO another slug (the "from" side of a merge) —
    #    those occurrences fold into the canonical target instead.
    promoted_slugs = set()
    if organization_id is not None:
        promoted_slugs = _promoted_child_slugs(
            db, parent_metric_id, organization_id
        )

    by_key: Dict[str, Dict[str, Any]] = {}
    for (scores,) in rows:
        if not isinstance(scores, dict):
            continue
        parent_entry = scores.get(parent_id_str)
        if not isinstance(parent_entry, dict):
            continue
        discovered = parent_entry.get("discovered_labels")
        if not isinstance(discovered, list):
            continue
        for entry in discovered:
            if not isinstance(entry, dict):
                continue
            raw_key = entry.get("key") or entry.get("name")
            key = _slug_label(raw_key)
            if not key:
                continue
            # Apply user merges + deletions first, THEN drop anything
            # that ended up on a real child slug. Order matters: a
            # candidate that was merged into a slug which has since
            # been promoted should disappear, not show up at the
            # canonical slug. An empty resolved key means the slug was
            # tombstoned via the delete endpoint.
            key = _resolve_alias(aliases, key)
            if not key or key in promoted_slugs:
                continue
            name = (entry.get("name") or "").strip() or key.replace("_", " ")
            description = (entry.get("description") or "").strip() or None
            sample = (entry.get("rationale") or "").strip() or None

            existing = by_key.get(key)
            if existing is None:
                # Track up to N=3 distinct rationales per candidate so
                # the Promote-to-child flow can pre-fill the new
                # sub-metric's rubric with concrete LLM examples
                # without the user copy-pasting from the row table.
                # ``sample_rationale`` is preserved for back-compat
                # with older clients; ``examples`` is the new field.
                examples = [sample] if sample else []
                by_key[key] = {
                    "key": key,
                    "name": name,
                    "description": description,
                    "sample_rationale": sample,
                    "examples": examples,
                    "count": 1,
                }
                continue

            existing["count"] += 1
            if not existing["description"] and description:
                existing["description"] = description
            if not existing["sample_rationale"] and sample:
                existing["sample_rationale"] = sample
            # Append distinct rationales (case-insensitive trim) up
            # to a small cap. Headroom is intentionally one above
            # what the UI surfaces (2) so we have a backup when the
            # first rationale is unhelpful.
            if sample:
                ex_list: List[str] = existing.setdefault("examples", [])
                if len(ex_list) < 3 and not any(
                    s.strip().lower() == sample.strip().lower() for s in ex_list
                ):
                    ex_list.append(sample)

    return sorted(
        by_key.values(),
        key=lambda item: (-item["count"], item["key"]),
    )


def _get_running_discovered_metrics(
    db: Session,
    eval_id: UUID,
    organization_id: Optional[UUID] = None,
    alias_map: Optional[Dict[str, str]] = None,
    *,
    from_cache: bool = False,
) -> List[Dict[str, Any]]:
    """Slug-deduped view of every discovered top-level metric in this eval.

    Mirrors :func:`_get_running_discovered_labels` but is keyed at the
    evaluation level (no ``parent_metric_id``). Walks each completed
    row's ``metric_scores[DISCOVERED_METRICS_KEY]`` list, folds entries
    that share the same slug (post-alias resolution), and suppresses
    slugs that already correspond to a real top-level :class:`Metric`
    in the organization.

    Each returned entry is shaped::

        {"key": "customer_satisfaction",
         "name": "Customer Satisfaction",
         "description": "...",
         "suggested_type": "boolean" | "rating" | "category",
         "sample_rationale": "...",
         "examples": ["..."],
         "count": 12}
    """

    aliases = alias_map or {}
    if from_cache:
        promoted_slugs: set[str] = set()
        if organization_id is not None:
            promoted_slugs = _promoted_top_level_metric_slugs(
                db, organization_id
            )
        from app.services.call_imports.discovered_running_cache import (
            load_running_metric_entries,
            project_discovered_entries,
        )

        return project_discovered_entries(
            load_running_metric_entries(db, eval_id),
            resolve_key=lambda raw: _resolve_alias(aliases, _slug_label(raw)),
            promoted_slugs=promoted_slugs,
        )

    from app.db_sharding.eval_rows import load_evaluation_rows_for_run

    eval_rows = load_evaluation_rows_for_run(db, eval_id)
    rows = [
        (row.metric_scores,)
        for row in eval_rows
        if row.status == CallImportRowStatus.COMPLETED.value
    ]

    promoted_slugs = set()
    if organization_id is not None:
        promoted_slugs = _promoted_top_level_metric_slugs(
            db, organization_id
        )
    aliases = alias_map or {}

    by_key: Dict[str, Dict[str, Any]] = {}
    for (scores,) in rows:
        if not isinstance(scores, dict):
            continue
        discovered = scores.get(DISCOVERED_METRICS_KEY)
        if not isinstance(discovered, list):
            continue
        for entry in discovered:
            if not isinstance(entry, dict):
                continue
            raw_key = entry.get("key") or entry.get("name")
            key = _slug_label(raw_key)
            if not key:
                continue
            # Apply user merges + deletions first, THEN drop anything
            # that ended up on an already-existing top-level metric
            # slug. Empty resolved key = tombstoned.
            key = _resolve_alias(aliases, key)
            if not key or key in promoted_slugs:
                continue
            name = (entry.get("name") or "").strip() or key.replace(
                "_", " "
            )
            description = (entry.get("description") or "").strip() or None
            sample = (entry.get("rationale") or "").strip() or None
            raw_type = str(entry.get("suggested_type") or "").strip().lower()
            if raw_type not in _DISCOVERED_METRIC_TYPES:
                raw_type = "boolean"

            existing = by_key.get(key)
            if existing is None:
                examples = [sample] if sample else []
                by_key[key] = {
                    "key": key,
                    "name": name,
                    "description": description,
                    "suggested_type": raw_type,
                    "sample_rationale": sample,
                    "examples": examples,
                    "count": 1,
                }
                continue

            existing["count"] += 1
            if not existing["description"] and description:
                existing["description"] = description
            if not existing["sample_rationale"] and sample:
                existing["sample_rationale"] = sample
            # Keep the most-frequently-suggested type. We don't track
            # per-type frequency yet; defer to the first non-default
            # type encountered when the existing entry has the default.
            if existing.get("suggested_type") == "boolean" and raw_type != "boolean":
                existing["suggested_type"] = raw_type
            if sample:
                ex_list: List[str] = existing.setdefault("examples", [])
                if len(ex_list) < 3 and not any(
                    s.strip().lower() == sample.strip().lower() for s in ex_list
                ):
                    ex_list.append(sample)

    return sorted(
        by_key.values(),
        key=lambda item: (-item["count"], item["key"]),
    )


@router.get(
    "/{eval_id}/discovered-labels",
    response_model=DiscoveredLabelsResponse,
    operation_id="getCallImportEvaluationDiscoveredLabels",
)
async def get_call_import_evaluation_discovered_labels(
    call_import_id: UUID,
    eval_id: UUID,
    parent_metric_id: UUID = Query(
        ...,
        description=(
            "Parent (category) metric whose LLM-discovered candidate "
            "sub-labels should be aggregated across rows."
        ),
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> DiscoveredLabelsResponse:
    """Aggregate candidate sub-labels the LLM discovered during this eval.

    Only meaningful for parents with ``allow_discovery=true``; for other
    parents we just return an empty ``items`` list rather than 400-ing
    so the frontend can call the endpoint unconditionally for every
    parent on the Flow tab without branching.
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

    alias_map = _alias_map_for_parent(evaluation, parent_metric_id)
    items_raw = _get_running_discovered_labels(
        db,
        eval_id,
        parent_metric_id,
        organization_id=organization_id,
        alias_map=alias_map,
    )
    items = [DiscoveredLabelItem(**item) for item in items_raw]
    return DiscoveredLabelsResponse(
        parent_metric_id=str(parent.id), items=items
    )


@router.post(
    "/{eval_id}/discovered-labels/merge",
    response_model=DiscoveredLabelsResponse,
    operation_id="mergeCallImportEvaluationDiscoveredLabels",
)
async def merge_call_import_evaluation_discovered_labels(
    call_import_id: UUID,
    eval_id: UUID,
    body: DiscoveredLabelMergeRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> DiscoveredLabelsResponse:
    """Rewrite every row's ``discovered_labels`` entry from from_key -> to_key.

    Idempotent — re-merging the same pair is a no-op. Discovered slugs
    inside per-row ``sequence`` arrays are also rewritten so the flow
    chart stays consistent with the panel. When a row already has
    ``to_key`` and we're merging ``from_key`` into it, we drop the
    ``from_key`` entry instead of producing two entries with the same
    slug.
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
            Metric.id == body.parent_metric_id,
            Metric.organization_id == organization_id,
        )
        .first()
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail="Parent metric not found in this organization.",
        )

    from_key = _slug_label(body.from_key)
    to_key = _slug_label(body.to_key)
    if not from_key or not to_key:
        raise HTTPException(
            status_code=400,
            detail="from_key and to_key must be non-empty slugs.",
        )
    if from_key == to_key:
        # No-op; just return the current aggregate so the client can
        # refresh its view.
        alias_map_existing = _alias_map_for_parent(evaluation, parent.id)
        items_raw = _get_running_discovered_labels(
            db,
            eval_id,
            body.parent_metric_id,
            organization_id=organization_id,
            alias_map=alias_map_existing,
        )
        return DiscoveredLabelsResponse(
            parent_metric_id=str(parent.id),
            items=[DiscoveredLabelItem(**item) for item in items_raw],
        )

    parent_id_str = str(parent.id)
    from app.db_sharding.eval_rows import foreach_evaluation_row_mutating

    def _merge_discovered_label_row(row: CallImportEvaluationRow) -> bool:
        scores = (
            row.metric_scores
            if isinstance(row.metric_scores, dict)
            else None
        )
        if not scores:
            return False
        parent_entry = scores.get(parent_id_str)
        if not isinstance(parent_entry, dict):
            return False

        mutated = False
        discovered = parent_entry.get("discovered_labels")
        if isinstance(discovered, list):
            kept: List[Dict[str, Any]] = []
            existing_to = next(
                (
                    e
                    for e in discovered
                    if isinstance(e, dict)
                    and _slug_label(e.get("key") or e.get("name")) == to_key
                ),
                None,
            )
            for entry in discovered:
                if not isinstance(entry, dict):
                    kept.append(entry)
                    continue
                key = _slug_label(entry.get("key") or entry.get("name"))
                if key == from_key:
                    if existing_to is not None:
                        mutated = True
                        continue
                    new_entry = dict(entry)
                    new_entry["key"] = to_key
                    kept.append(new_entry)
                    mutated = True
                else:
                    kept.append(entry)
            if mutated:
                parent_entry["discovered_labels"] = kept

        seq = parent_entry.get("sequence")
        if isinstance(seq, list):
            new_seq: List[str] = []
            seq_changed = False
            last_added: Optional[str] = None
            for item in seq:
                if isinstance(item, str) and _slug_label(item) == from_key:
                    seq_changed = True
                    if last_added == to_key:
                        continue
                    new_seq.append(to_key)
                    last_added = to_key
                else:
                    new_seq.append(item)
                    last_added = (
                        _slug_label(item) if isinstance(item, str) else None
                    )
            if seq_changed:
                parent_entry["sequence"] = new_seq
                mutated = True

        if mutated:
            row.metric_scores = dict(scores)
        return mutated

    foreach_evaluation_row_mutating(db, eval_id, _merge_discovered_label_row)

    # Persist the merge at the evaluation level too. This is what makes
    # the merge survive future scoring: rows that finish AFTER this
    # call (e.g. retries, in-flight workers) will go through the
    # alias map in the API surface even if the per-row JSON they
    # write still mentions ``from_key``. We chain through any existing
    # alias so merging A→B and then B→C resolves A→C in the panel.
    raw_aliases = (
        evaluation.discovered_label_aliases
        if isinstance(evaluation.discovered_label_aliases, dict)
        else {}
    )
    aliases_top = dict(raw_aliases)
    parent_aliases = dict(aliases_top.get(parent_id_str) or {})
    # Resolve transitively: if to_key itself was previously merged into
    # something else, point from_key at the canonical end-of-chain.
    canonical_to = _resolve_alias(parent_aliases, to_key)
    parent_aliases[from_key] = canonical_to
    # Re-target any earlier aliases that pointed AT from_key — without
    # this, A→B and then B→C would leave A still pointing to B (now a
    # broken pointer because B is gone). Rewriting them keeps the
    # alias map self-consistent.
    for k, v in list(parent_aliases.items()):
        if v == from_key:
            parent_aliases[k] = canonical_to
    aliases_top[parent_id_str] = parent_aliases
    evaluation.discovered_label_aliases = aliases_top

    stamp_evaluation_actor(evaluation, principal)
    db.commit()

    alias_map_after = _alias_map_for_parent(evaluation, parent.id)
    items_raw = _get_running_discovered_labels(
        db,
        eval_id,
        body.parent_metric_id,
        organization_id=organization_id,
        alias_map=alias_map_after,
    )
    return DiscoveredLabelsResponse(
        parent_metric_id=str(parent.id),
        items=[DiscoveredLabelItem(**item) for item in items_raw],
    )


@router.post(
    "/{eval_id}/discovered-labels/delete",
    response_model=DiscoveredLabelsResponse,
    operation_id="deleteCallImportEvaluationDiscoveredLabel",
)
async def delete_call_import_evaluation_discovered_label(
    call_import_id: UUID,
    eval_id: UUID,
    body: DiscoveredLabelDeleteRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> DiscoveredLabelsResponse:
    """Tombstone a single LLM-discovered candidate for this evaluation.

    Symmetric with the merge endpoint, but instead of redirecting the
    slug at another candidate we mark it as deleted. After this call:

      * the slug is stripped from every row's
        ``metric_scores[parent].discovered_labels`` list, and from
        every row's ``sequence`` array (so the flow chart no longer
        draws a node for it);
      * the slug is recorded in
        ``evaluation.discovered_label_aliases[parent][slug] = ""``
        so any worker that finishes a row AFTER this call (e.g. a row
        still in flight when the user clicked Delete) silently drops
        the slug instead of resurrecting it.

    Idempotent: deleting an already-deleted slug is a no-op.
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
            Metric.id == body.parent_metric_id,
            Metric.organization_id == organization_id,
        )
        .first()
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail="Parent metric not found in this organization.",
        )

    target_key = _slug_label(body.key)
    if not target_key:
        raise HTTPException(
            status_code=400,
            detail="key must be a non-empty slug.",
        )

    parent_id_str = str(parent.id)
    from app.db_sharding.eval_rows import foreach_evaluation_row_mutating

    def _delete_discovered_label_row(row: CallImportEvaluationRow) -> bool:
        scores = (
            row.metric_scores
            if isinstance(row.metric_scores, dict)
            else None
        )
        if not scores:
            return False
        parent_entry = scores.get(parent_id_str)
        if not isinstance(parent_entry, dict):
            return False

        mutated = False
        discovered = parent_entry.get("discovered_labels")
        if isinstance(discovered, list):
            kept = [
                e
                for e in discovered
                if not (
                    isinstance(e, dict)
                    and _slug_label(e.get("key") or e.get("name"))
                    == target_key
                )
            ]
            if len(kept) != len(discovered):
                parent_entry["discovered_labels"] = kept
                mutated = True

        seq = parent_entry.get("sequence")
        if isinstance(seq, list):
            new_seq: List[str] = []
            seq_changed = False
            last_added: Optional[str] = None
            for item in seq:
                if isinstance(item, str) and _slug_label(item) == target_key:
                    seq_changed = True
                    continue
                if isinstance(item, str):
                    norm = _slug_label(item)
                    if norm == last_added:
                        seq_changed = True
                        continue
                    last_added = norm
                new_seq.append(item)
            if seq_changed:
                parent_entry["sequence"] = new_seq
                mutated = True

        if mutated:
            row.metric_scores = dict(scores)
        return mutated

    foreach_evaluation_row_mutating(db, eval_id, _delete_discovered_label_row)

    # 3. Persist the tombstone on the evaluation so workers that finish
    # later don't re-surface the deleted slug. We also retarget any
    # existing aliases whose ``to_key`` was the deleted slug — without
    # this, a previous merge that pointed at this slug would leave a
    # dangling pointer.
    raw_aliases = (
        evaluation.discovered_label_aliases
        if isinstance(evaluation.discovered_label_aliases, dict)
        else {}
    )
    aliases_top = dict(raw_aliases)
    parent_aliases = dict(aliases_top.get(parent_id_str) or {})
    parent_aliases[target_key] = ""  # deletion sentinel
    for k, v in list(parent_aliases.items()):
        if v == target_key:
            parent_aliases[k] = ""
    aliases_top[parent_id_str] = parent_aliases
    evaluation.discovered_label_aliases = aliases_top

    stamp_evaluation_actor(evaluation, principal)
    db.commit()

    alias_map_after = _alias_map_for_parent(evaluation, parent.id)
    items_raw = _get_running_discovered_labels(
        db,
        eval_id,
        body.parent_metric_id,
        organization_id=organization_id,
        alias_map=alias_map_after,
    )
    return DiscoveredLabelsResponse(
        parent_metric_id=str(parent.id),
        items=[DiscoveredLabelItem(**item) for item in items_raw],
    )


# ---------------------------------------------------------------------------
# Discovered TOP-LEVEL METRICS (per-evaluation discovery)
#
# These endpoints are the parallel of the discovered-labels trio above but
# scoped to the evaluation as a whole instead of to a parent metric. They
# all live under ``/{eval_id}/discovered-metrics`` and operate on the
# reserved ``DISCOVERED_METRICS_KEY`` slot of each per-row
# ``metric_scores`` plus the flat ``CallImportEvaluation.discovered_metric_aliases``
# map (no parent-id nesting).
# ---------------------------------------------------------------------------


def _flat_metric_aliases(
    evaluation: CallImportEvaluation,
) -> Dict[str, str]:
    """Pull the flat ``{from_slug: to_slug}`` map for an evaluation."""
    raw = getattr(evaluation, "discovered_metric_aliases", None)
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in raw.items()
        if isinstance(k, str) and isinstance(v, str)
    }


@router.get(
    "/{eval_id}/discovered-metrics",
    response_model=DiscoveredMetricsResponse,
    operation_id="getCallImportEvaluationDiscoveredMetrics",
)
async def get_call_import_evaluation_discovered_metrics(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> DiscoveredMetricsResponse:
    """Aggregate top-level metric candidates the LLM discovered during this eval.

    Returns an empty ``items`` list when the evaluation did not opt
    into top-level metric discovery; this keeps the frontend able to
    call the endpoint unconditionally without branching on the
    evaluation's ``discover_new_metrics`` flag.
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

    if not bool(getattr(evaluation, "discover_new_metrics", False)):
        return DiscoveredMetricsResponse(evaluation_id=evaluation.id, items=[])

    items_raw = _get_running_discovered_metrics(
        db,
        eval_id,
        organization_id=organization_id,
        alias_map=_flat_metric_aliases(evaluation),
    )
    return DiscoveredMetricsResponse(
        evaluation_id=evaluation.id,
        items=[DiscoveredMetricItem(**item) for item in items_raw],
    )


@router.post(
    "/{eval_id}/discovered-metrics/merge",
    response_model=DiscoveredMetricsResponse,
    operation_id="mergeCallImportEvaluationDiscoveredMetrics",
)
async def merge_call_import_evaluation_discovered_metrics(
    call_import_id: UUID,
    eval_id: UUID,
    body: DiscoveredMetricMergeRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> DiscoveredMetricsResponse:
    """Rewrite every row's ``__discovered_metrics__`` entry from→to.

    Mirrors the discovered-labels merge endpoint but operates on the
    flat top-level metric list. Idempotent — re-merging is a no-op.
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

    from_key = _slug_label(body.from_key)
    to_key = _slug_label(body.to_key)
    if not from_key or not to_key:
        raise HTTPException(
            status_code=400,
            detail="from_key and to_key must be non-empty slugs.",
        )
    if from_key == to_key:
        items_raw = _get_running_discovered_metrics(
            db,
            eval_id,
            organization_id=organization_id,
            alias_map=_flat_metric_aliases(evaluation),
        )
        return DiscoveredMetricsResponse(
            evaluation_id=evaluation.id,
            items=[DiscoveredMetricItem(**item) for item in items_raw],
        )

    from app.db_sharding.eval_rows import foreach_evaluation_row_mutating

    def _merge_discovered_metric_row(row: CallImportEvaluationRow) -> bool:
        scores = (
            row.metric_scores
            if isinstance(row.metric_scores, dict)
            else None
        )
        if not scores:
            return False
        discovered = scores.get(DISCOVERED_METRICS_KEY)
        if not isinstance(discovered, list):
            return False

        kept: List[Dict[str, Any]] = []
        mutated = False
        existing_to = next(
            (
                e
                for e in discovered
                if isinstance(e, dict)
                and _slug_label(e.get("key") or e.get("name")) == to_key
            ),
            None,
        )
        for entry in discovered:
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            key = _slug_label(entry.get("key") or entry.get("name"))
            if key == from_key:
                if existing_to is not None:
                    mutated = True
                    continue
                new_entry = dict(entry)
                new_entry["key"] = to_key
                kept.append(new_entry)
                mutated = True
            else:
                kept.append(entry)
        if mutated:
            scores[DISCOVERED_METRICS_KEY] = kept
            row.metric_scores = dict(scores)
        return mutated

    foreach_evaluation_row_mutating(db, eval_id, _merge_discovered_metric_row)

    raw_aliases = (
        evaluation.discovered_metric_aliases
        if isinstance(evaluation.discovered_metric_aliases, dict)
        else {}
    )
    aliases = dict(raw_aliases)
    canonical_to = _resolve_alias(aliases, to_key)
    aliases[from_key] = canonical_to
    for k, v in list(aliases.items()):
        if v == from_key:
            aliases[k] = canonical_to
    evaluation.discovered_metric_aliases = aliases

    stamp_evaluation_actor(evaluation, principal)
    db.commit()

    items_raw = _get_running_discovered_metrics(
        db,
        eval_id,
        organization_id=organization_id,
        alias_map=_flat_metric_aliases(evaluation),
    )
    return DiscoveredMetricsResponse(
        evaluation_id=evaluation.id,
        items=[DiscoveredMetricItem(**item) for item in items_raw],
    )


@router.post(
    "/{eval_id}/discovered-metrics/delete",
    response_model=DiscoveredMetricsResponse,
    operation_id="deleteCallImportEvaluationDiscoveredMetric",
)
async def delete_call_import_evaluation_discovered_metric(
    call_import_id: UUID,
    eval_id: UUID,
    body: DiscoveredMetricDeleteRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> DiscoveredMetricsResponse:
    """Tombstone a single LLM-discovered top-level metric candidate."""

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

    target_key = _slug_label(body.key)
    if not target_key:
        raise HTTPException(
            status_code=400,
            detail="key must be a non-empty slug.",
        )

    from app.db_sharding.eval_rows import foreach_evaluation_row_mutating

    def _delete_discovered_metric_row(row: CallImportEvaluationRow) -> bool:
        scores = (
            row.metric_scores
            if isinstance(row.metric_scores, dict)
            else None
        )
        if not scores:
            return False
        discovered = scores.get(DISCOVERED_METRICS_KEY)
        if not isinstance(discovered, list):
            return False
        kept = [
            e
            for e in discovered
            if not (
                isinstance(e, dict)
                and _slug_label(e.get("key") or e.get("name"))
                == target_key
            )
        ]
        if len(kept) == len(discovered):
            return False
        if kept:
            scores[DISCOVERED_METRICS_KEY] = kept
        else:
            scores.pop(DISCOVERED_METRICS_KEY, None)
        row.metric_scores = dict(scores)
        return True

    foreach_evaluation_row_mutating(db, eval_id, _delete_discovered_metric_row)

    raw_aliases = (
        evaluation.discovered_metric_aliases
        if isinstance(evaluation.discovered_metric_aliases, dict)
        else {}
    )
    aliases = dict(raw_aliases)
    aliases[target_key] = ""  # tombstone
    for k, v in list(aliases.items()):
        if v == target_key:
            aliases[k] = ""
    evaluation.discovered_metric_aliases = aliases

    stamp_evaluation_actor(evaluation, principal)
    db.commit()

    items_raw = _get_running_discovered_metrics(
        db,
        eval_id,
        organization_id=organization_id,
        alias_map=_flat_metric_aliases(evaluation),
    )
    return DiscoveredMetricsResponse(
        evaluation_id=evaluation.id,
        items=[DiscoveredMetricItem(**item) for item in items_raw],
    )

