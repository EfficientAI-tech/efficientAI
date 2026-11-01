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
    _serialize_selected_metric_ids,
)


def _evaluation_rows_for_period(
    db: Session,
    evaluation_id: UUID,
) -> list[tuple[CallImportEvaluationRow, CallImportRow]]:
    from app.db_sharding.scatter_gather import load_evaluation_row_pairs
    from app.db_sharding.sessions import is_sharding_enabled

    if is_sharding_enabled():
        return sorted(
            load_evaluation_row_pairs(db, evaluation_id),
            key=lambda pair: int(pair[1].row_index or 0),
        )
    return (
        db.query(CallImportEvaluationRow, CallImportRow)
        .join(
            CallImportRow,
            CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
        )
        .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
        .order_by(CallImportRow.row_index.asc())
        .all()
    )


def _metric_is_user_insight(metric: Metric) -> bool:
    if (getattr(metric, "metric_category", "quality") or "quality") == "user_insight":
        return True
    text_value = " ".join(
        str(part or "").lower()
        for part in (getattr(metric, "name", ""), getattr(metric, "description", ""))
    )
    normalized = text_value.replace("-", " ").replace("_", " ")
    phrases = (
        "call context",
        "caller context",
        "product identification",
        "out of scope",
        "identity match",
        "user identity",
        "caller identity",
        "frustration trigger",
        "video call offer",
        "video call reception",
    )
    return any(phrase in normalized for phrase in phrases)


def _baseline_candidate_evaluations(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    current_evaluation: CallImportEvaluation,
    current_period_start: Optional[date],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    candidates = (
        db.query(CallImportEvaluation, CallImport)
        .join(CallImport, CallImport.id == CallImportEvaluation.call_import_id)
        .filter(
            CallImportEvaluation.organization_id == organization_id,
            CallImport.workspace_id == workspace_id,
            CallImportEvaluation.id != current_evaluation.id,
            CallImportEvaluation.status == "completed",
            CallImportEvaluation.completed_rows > 0,
        )
        .order_by(desc(CallImportEvaluation.created_at))
        .limit(limit * 3)
        .all()
    )
    items: list[dict[str, Any]] = []
    for candidate_eval, candidate_import in candidates:
        rows = _evaluation_rows_for_period(db, candidate_eval.id)
        period_start, period_end, period_label, period_display = _report_period_from_rows(rows)
        if current_period_start and period_start and period_start >= current_period_start:
            continue
        dataset = (
            (candidate_import.dataset or "").strip()
            or (candidate_import.original_filename or candidate_import.filename or "").strip()
            or "Unknown dataset"
        )
        evaluation_name = (
            (candidate_eval.name or "").strip()
            or str(candidate_eval.id)[:8]
        )
        items.append(
            {
                "evaluation_id": str(candidate_eval.id),
                "name": evaluation_name,
                "dataset": dataset,
                "period_label": period_label,
                "period_start": period_start,
                "period_end": period_end,
                "period_display": period_display,
                "completed_rows": int(candidate_eval.completed_rows or 0),
                "created_at": candidate_eval.created_at,
                "is_default": False,
            }
        )
        if len(items) >= limit:
            break
    items.sort(
        key=lambda item: (
            item["period_start"] or date.min,
            item["created_at"] or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    if items:
        items[0]["is_default"] = True
    return items


def _resolve_baseline_evaluation(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    current_evaluation: CallImportEvaluation,
    current_period_start: Optional[date],
    baseline_evaluation_id: Optional[str],
) -> Optional[CallImportEvaluation]:
    candidates = _baseline_candidate_evaluations(
        db,
        organization_id,
        workspace_id,
        current_evaluation,
        current_period_start,
    )
    allowed_ids = {item["evaluation_id"] for item in candidates}
    if baseline_evaluation_id:
        baseline_id = str(baseline_evaluation_id).strip()
        if baseline_id not in allowed_ids:
            raise HTTPException(
                status_code=400,
                detail="Selected baseline evaluation is not a valid prior run for this report.",
            )
        return (
            db.query(CallImportEvaluation)
            .filter(
                CallImportEvaluation.id == UUID(baseline_id),
                CallImportEvaluation.organization_id == organization_id,
            )
            .first()
        )
    if not candidates:
        return None
    default_id = candidates[0]["evaluation_id"]
    return (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == UUID(default_id),
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )


def _benchmark_context_for_evaluation(
    db: Session,
    baseline_evaluation: Optional[CallImportEvaluation],
) -> Optional[dict[str, str]]:
    if baseline_evaluation is None:
        return None
    baseline_import = (
        db.query(CallImport)
        .filter(CallImport.id == baseline_evaluation.call_import_id)
        .first()
    )
    rows = _evaluation_rows_for_period(db, baseline_evaluation.id)
    period_start, _period_end, period_label, _period_display = _report_period_from_rows(rows)
    dataset = (
        (baseline_import.dataset or "").strip()
        if baseline_import and baseline_import.dataset
        else None
    )
    filename = (
        (baseline_import.original_filename or baseline_import.filename or "").strip()
        if baseline_import
        else None
    )
    evaluation_label = (
        (baseline_evaluation.name or "").strip()
        if baseline_evaluation.name
        else str(baseline_evaluation.id)[:8]
    )
    period = period_label or (
        period_start.isoformat() if period_start else "previous report"
    )
    return {
        "dataset": dataset or filename or "Unknown dataset",
        "evaluation": evaluation_label,
        "evaluation_id": str(baseline_evaluation.id),
        "period": period,
    }


def _period_deltas_from_evaluation(
    db: Session,
    baseline_evaluation: CallImportEvaluation,
    current_metric_aggregates: list[dict[str, Any]],
    current_evaluation: CallImportEvaluation,
    current_eval_rows: List[CallImportEvaluationRow],
) -> dict[str, dict[str, str]]:
    baseline_rows = _evaluation_rows_for_period(db, baseline_evaluation.id)
    baseline_eval_rows = [eval_row for eval_row, _source_row in baseline_rows]
    baseline_aggregate_models = _compute_metric_aggregates(
        db,
        baseline_evaluation,
        baseline_eval_rows,
    )
    baseline_metric_aggregates = [
        _aggregate_to_dict(aggregate) for aggregate in baseline_aggregate_models
    ]
    _metrics, _aggs, policies, _source, _child_map = _clustering_context(
        db, current_evaluation, current_eval_rows
    )
    metric_by_id = {str(m.id): m for m in _metrics}
    current_by_id = {
        str(item.get("metric_id")): item for item in current_metric_aggregates
    }
    previous_by_id = {
        str(item.get("metric_id")): item
        for item in baseline_metric_aggregates
        if isinstance(item, dict)
    }
    deltas: dict[str, dict[str, str]] = {}
    for metric_id, current in current_by_id.items():
        metric = metric_by_id.get(metric_id)
        policy = policies.get(metric_id)
        previous_raw = previous_by_id.get(metric_id)
        if metric is None or policy is None:
            deltas[metric_id] = {
                "label": "No previous-week baseline",
                "detail": "No comparable prior report snapshot was found.",
            }
            continue
        current_pct = failure_rate_percent_from_rows(
            current_eval_rows, metric, policy
        )
        previous_pct = failure_rate_percent_from_rows(
            baseline_eval_rows, metric, policy
        )
        if current_pct is None or previous_pct is None:
            current_pct = current_pct or _aggregate_primary_percent(current, policy)
            previous_pct = (
                previous_pct or _aggregate_primary_percent(previous_raw, policy)
                if previous_raw
                else None
            )
        if current_pct is None or previous_pct is None:
            deltas[metric_id] = {
                "label": "No previous-week baseline",
                "detail": "No comparable prior report snapshot was found.",
            }
            continue
        delta = current_pct - previous_pct
        sign = "+" if delta >= 0 else ""
        deltas[metric_id] = {
            "label": f"{sign}{delta:.1f} pp",
            "detail": (
                f"Current report {current_pct:.1f}% vs previous report "
                f"{previous_pct:.1f}%"
            ),
        }
    return deltas


_DELTA_EXPLANATION_SYSTEM_PROMPT = (
    "You are a senior conversation-analytics reviewer. You will receive "
    "week-over-week metric failure-rate deltas plus reconciled failure "
    "cluster context per metric.\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "explanations": {"<metric_id>": "<1-2 sentence explanation of why the delta likely occurred>"}\n'
    "}\n\n"
    "Constraints:\n"
    "- Only include metrics supplied in the prompt.\n"
    "- Cluster labels are generated independently each run and are NOT stable "
    "IDs. Never compare an unmatched current label to 0% baseline.\n"
    "- Use matched_theme_shifts for label-aligned comparisons, "
    "gap_label_shifts for structural shifts, and new_themes_current_period "
    "for themes that emerged without a baseline match.\n"
    "- If reconciliation is uncertain, explain using the numeric delta and "
    "gap_label_shifts only.\n"
    "- Keep each explanation to 1-2 short sentences (~220 chars).\n"
    "- Vendor-safe, factual language; no markdown."
)


def _period_delta_explanation_cache_key(
    baseline_evaluation_id: UUID,
    *,
    completed_rows: int,
    baseline_completed_rows: int,
) -> str:
    return (
        f"{baseline_evaluation_id}:{completed_rows}:"
        f"{baseline_completed_rows}:reconciled-v2"
    )


def _normalize_cluster_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (label or "").lower()).strip()


_CLUSTER_LABEL_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "during",
        "while",
        "with",
        "for",
        "from",
        "into",
        "general",
        "user",
        "bot",
        "agent",
    }
)


def _cluster_label_tokens(label: str) -> set[str]:
    return {
        token
        for token in _normalize_cluster_label(label).split()
        if token and token not in _CLUSTER_LABEL_STOPWORDS and len(token) > 2
    }


def _cluster_label_similarity(left: str, right: str) -> float:
    tokens_left = _cluster_label_tokens(left)
    tokens_right = _cluster_label_tokens(right)
    if not tokens_left or not tokens_right:
        return 0.0
    intersection = tokens_left & tokens_right
    if not intersection:
        return 0.0
    union = tokens_left | tokens_right
    jaccard = len(intersection) / len(union)
    smaller = tokens_left if len(tokens_left) <= len(tokens_right) else tokens_right
    overlap_ratio = len(intersection) / len(smaller)
    return max(jaccard, overlap_ratio * 0.85)


def _group_clusters_by_gap_label(
    clusters: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for cluster in clusters:
        gap_label = str(cluster.get("gap_label") or "UNKNOWN")
        grouped.setdefault(gap_label, []).append(cluster)
    return grouped


def _append_matched_cluster_pair(
    matched: list[dict[str, Any]],
    current: dict[str, Any],
    baseline: dict[str, Any],
    *,
    match_confidence: float,
    match_method: str,
) -> None:
    matched.append(
        {
            "current_label": current.get("label"),
            "baseline_label": baseline.get("label"),
            "gap_label": current.get("gap_label") or baseline.get("gap_label"),
            "current_share_pct": current.get("share_pct"),
            "baseline_share_pct": baseline.get("share_pct"),
            "share_delta_pp": round(
                float(current.get("share_pct") or 0.0)
                - float(baseline.get("share_pct") or 0.0),
                1,
            ),
            "match_confidence": round(match_confidence, 2),
            "match_method": match_method,
        }
    )


def _aggregate_share_by_gap_label(
    clusters: list[dict[str, Any]],
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for cluster in clusters:
        gap_label = str(cluster.get("gap_label") or "UNKNOWN")
        totals[gap_label] = totals.get(gap_label, 0.0) + float(
            cluster.get("share_pct") or 0.0
        )
    return {gap: round(share, 1) for gap, share in totals.items()}


def _reconcile_cluster_periods(
    current_clusters: list[dict[str, Any]],
    baseline_clusters: list[dict[str, Any]],
    *,
    similarity_threshold: float = 0.35,
) -> dict[str, Any]:
    """Align independently-generated cluster labels before delta explanation."""
    matched: list[dict[str, Any]] = []
    current_unmatched = list(current_clusters)
    remaining_baseline = list(baseline_clusters)

    current_by_gap = _group_clusters_by_gap_label(current_unmatched)
    baseline_by_gap = _group_clusters_by_gap_label(remaining_baseline)
    for gap_label in list(current_by_gap):
        current_group = current_by_gap.get(gap_label) or []
        baseline_group = baseline_by_gap.get(gap_label) or []
        if len(current_group) != 1 or len(baseline_group) != 1:
            continue
        current = current_group[0]
        baseline = baseline_group[0]
        _append_matched_cluster_pair(
            matched,
            current,
            baseline,
            match_confidence=0.75,
            match_method="single_cluster_per_gap_label",
        )
        current_unmatched.remove(current)
        remaining_baseline.remove(baseline)
        current_by_gap[gap_label] = []
        baseline_by_gap[gap_label] = []

    for current in list(current_unmatched):
        best_idx: Optional[int] = None
        best_score = 0.0
        for idx, baseline in enumerate(remaining_baseline):
            score = _cluster_label_similarity(
                str(current.get("label") or ""),
                str(baseline.get("label") or ""),
            )
            if current.get("gap_label") == baseline.get("gap_label"):
                score += 0.1
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx is not None and best_score >= similarity_threshold:
            baseline = remaining_baseline.pop(best_idx)
            _append_matched_cluster_pair(
                matched,
                current,
                baseline,
                match_confidence=best_score,
                match_method="label_similarity",
            )

    matched_current_labels = {
        str(item.get("current_label") or "") for item in matched
    }
    matched_baseline_labels = {
        str(item.get("baseline_label") or "") for item in matched
    }
    current_unmatched = [
        cluster
        for cluster in current_clusters
        if str(cluster.get("label") or "") not in matched_current_labels
    ]
    remaining_baseline = [
        cluster
        for cluster in baseline_clusters
        if str(cluster.get("label") or "") not in matched_baseline_labels
    ]

    new_themes = [
        {
            "label": cluster.get("label"),
            "gap_label": cluster.get("gap_label"),
            "share_pct": cluster.get("share_pct"),
            "note": "New theme in current period (no close baseline match).",
        }
        for cluster in current_unmatched
    ]

    retired_themes = [
        {
            "label": baseline.get("label"),
            "gap_label": baseline.get("gap_label"),
            "share_pct": baseline.get("share_pct"),
            "note": "Theme present in baseline only (retired or renamed).",
        }
        for baseline in remaining_baseline
    ]

    current_gap = _aggregate_share_by_gap_label(current_clusters)
    baseline_gap = _aggregate_share_by_gap_label(baseline_clusters)
    gap_label_shifts: dict[str, dict[str, float]] = {}
    for gap_label in set(current_gap) | set(baseline_gap):
        current_share = current_gap.get(gap_label, 0.0)
        baseline_share = baseline_gap.get(gap_label, 0.0)
        if abs(current_share - baseline_share) >= 0.5:
            gap_label_shifts[gap_label] = {
                "current_share_pct": current_share,
                "baseline_share_pct": baseline_share,
                "share_delta_pp": round(current_share - baseline_share, 1),
            }

    return {
        "matched_theme_shifts": matched,
        "new_themes_current_period": new_themes,
        "retired_themes_baseline_period": retired_themes,
        "gap_label_shifts": gap_label_shifts,
        "reconciliation_note": (
            "Cluster labels are generated independently each run and may "
            "rename the same failure mode. Do not treat unmatched current "
            "labels as 0% in the baseline period."
        ),
    }


def _load_period_delta_explanations_cache(
    evaluation: CallImportEvaluation,
    cache_key: str,
) -> Optional[dict[str, str]]:
    raw = getattr(evaluation, "period_delta_explanations", None)
    if not isinstance(raw, dict):
        return None
    entry = raw.get(cache_key)
    if not isinstance(entry, dict):
        return None
    explanations_raw = entry.get("explanations")
    if not isinstance(explanations_raw, dict):
        return None
    return {
        str(metric_id): str(why).strip()
        for metric_id, why in explanations_raw.items()
        if str(metric_id).strip() and isinstance(why, str) and why.strip()
    }


def _save_period_delta_explanations_cache(
    db: Session,
    evaluation: CallImportEvaluation,
    cache_key: str,
    explanations: dict[str, str],
) -> None:
    raw = evaluation.period_delta_explanations
    if not isinstance(raw, dict):
        raw = {}
    updated = dict(raw)
    updated[cache_key] = {
        "explanations": explanations,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    evaluation.period_delta_explanations = updated
    flag_modified(evaluation, "period_delta_explanations")
    db.commit()


def _cluster_summary_for_metric(
    state: Optional[EvaluationMetricClustersState],
    metric_id: str,
) -> list[dict[str, Any]]:
    if state is None or state.status != "completed":
        return []
    for group in state.groups:
        if str(group.metric_id) != metric_id:
            continue
        return [
            {
                "label": cluster.label,
                "gap_label": cluster.gap_label,
                "share_pct": round(cluster.share_pct, 1),
                "count": cluster.count,
            }
            for cluster in group.clusters[:5]
        ]
    return []


def _merge_delta_why(
    raw_deltas: dict[str, dict[str, str]],
    explanations: dict[str, str],
) -> dict[str, dict[str, str]]:
    if not explanations:
        return raw_deltas
    merged: dict[str, dict[str, str]] = {}
    for metric_id, delta in raw_deltas.items():
        updated = dict(delta)
        why = explanations.get(metric_id)
        if why:
            updated["why"] = why
        merged[metric_id] = updated
    return merged


def _explain_period_deltas(
    db: Session,
    organization_id: UUID,
    evaluation: CallImportEvaluation,
    baseline_evaluation: CallImportEvaluation,
    raw_deltas: dict[str, dict[str, str]],
    *,
    min_delta_pp: float = 0.5,
) -> dict[str, dict[str, str]]:
    """Attach ``why`` explanations to period deltas using cached LLM output."""
    if not raw_deltas:
        return raw_deltas

    cache_key = _period_delta_explanation_cache_key(
        baseline_evaluation.id,
        completed_rows=evaluation.completed_rows,
        baseline_completed_rows=baseline_evaluation.completed_rows,
    )
    cached = _load_period_delta_explanations_cache(evaluation, cache_key)
    if cached is not None:
        return _merge_delta_why(raw_deltas, cached)

    from app.api.v1.routes.call_import_evaluations.clusters import (
        _metric_clusters_payload,
    )

    current_clusters = _metric_clusters_payload(evaluation)
    baseline_clusters = _metric_clusters_payload(baseline_evaluation)
    metrics_for_prompt: list[dict[str, Any]] = []
    for metric_id, delta in raw_deltas.items():
        label = delta.get("label") or ""
        if "No previous-week baseline" in label:
            continue
        match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*pp", label)
        if match and abs(float(match.group(1))) < min_delta_pp:
            continue
        current_summary = _cluster_summary_for_metric(current_clusters, metric_id)
        baseline_summary = _cluster_summary_for_metric(baseline_clusters, metric_id)
        if not current_summary and not baseline_summary:
            continue
        cluster_reconciliation = _reconcile_cluster_periods(
            current_summary,
            baseline_summary,
        )
        metrics_for_prompt.append(
            {
                "metric_id": metric_id,
                "delta_label": label,
                "delta_detail": delta.get("detail") or "",
                "cluster_reconciliation": cluster_reconciliation,
            }
        )

    if not metrics_for_prompt:
        return raw_deltas

    provider_hint: Optional[str] = None
    model_hint: Optional[str] = None
    tldr_raw = evaluation.tldr_summary
    if isinstance(tldr_raw, dict):
        if isinstance(tldr_raw.get("provider"), str):
            provider_hint = tldr_raw["provider"]
        if isinstance(tldr_raw.get("model"), str):
            model_hint = tldr_raw["model"]

    from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request
    from app.services.call_import_user_insights import _call_llm, _parse_json_object
    from app.services.usage.call_import_context import (
        call_import_evaluation_usage_context,
    )

    provider_enum, model_str = get_llm_provider_and_model_for_request(
        organization_id, db, provider_hint, model_hint
    )
    usage_ctx = call_import_evaluation_usage_context(
        organization_id=organization_id,
        workspace_id=evaluation.workspace_id,
        evaluation_id=evaluation.id,
        call_import_id=evaluation.call_import_id,
    )
    try:
        text = _call_llm(
            db,
            organization_id,
            provider_enum,
            model_str,
            [
                {"role": "system", "content": _DELTA_EXPLANATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"metrics": metrics_for_prompt},
                        ensure_ascii=False,
                        default=str,
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=900,
            usage_ctx=usage_ctx,
        )
    except Exception as exc:
        logger.warning("[PeriodDeltaExplain] LLM call failed: {}", exc)
        return raw_deltas

    parsed = _parse_json_object(text)
    explanations_raw = parsed.get("explanations")
    explanations: dict[str, str] = {}
    if isinstance(explanations_raw, dict):
        for metric_id, why in explanations_raw.items():
            if isinstance(why, str) and why.strip():
                explanations[str(metric_id)] = why.strip()

    if explanations:
        _save_period_delta_explanations_cache(
            db, evaluation, cache_key, explanations
        )
    return _merge_delta_why(raw_deltas, explanations)


def _period_deltas_with_explanations(
    db: Session,
    organization_id: UUID,
    evaluation: CallImportEvaluation,
    baseline_evaluation: CallImportEvaluation,
    raw_deltas: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    return _explain_period_deltas(
        db,
        organization_id,
        evaluation,
        baseline_evaluation,
        raw_deltas,
    )


def _benchmark_context_for_snapshot(
    db: Session,
    previous_snapshot: Optional[CallImportEvaluationReportSnapshot],
) -> Optional[dict[str, str]]:
    if previous_snapshot is None:
        return None
    previous_import = (
        db.query(CallImport)
        .filter(CallImport.id == previous_snapshot.call_import_id)
        .first()
    )
    previous_eval = (
        db.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == previous_snapshot.evaluation_id)
        .first()
    )
    dataset = (
        (previous_import.dataset or "").strip()
        if previous_import and previous_import.dataset
        else None
    )
    filename = (
        (previous_import.original_filename or previous_import.filename or "").strip()
        if previous_import
        else None
    )
    evaluation_label = (
        (previous_eval.name or "").strip()
        if previous_eval and previous_eval.name
        else str(previous_snapshot.evaluation_id)[:8]
    )
    period = previous_snapshot.period_label or (
        previous_snapshot.period_start.isoformat()
        if previous_snapshot.period_start
        else "previous report"
    )
    return {
        "dataset": dataset or filename or "Unknown dataset",
        "evaluation": evaluation_label,
        "evaluation_id": str(previous_snapshot.evaluation_id),
        "period": period,
    }


def _clamp_prose_to_sentences(
    text: str,
    *,
    max_sentences: int = 3,
    max_chars: int = 300,
) -> str:
    """Keep concise audit/TLDR prose within sentence and character limits."""
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    cleaned = re.sub(r"\s*\n+\s*", " ", cleaned).strip()
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
        if sentence.strip()
    ]
    if sentences:
        result = " ".join(sentences[:max_sentences]).strip()
    else:
        result = cleaned
    if len(result) > max_chars:
        trimmed = result[: max_chars - 3].rsplit(" ", 1)[0].rstrip(".,;:")
        result = f"{trimmed}..." if trimmed else result[:max_chars]
    return result


def _audit_summary_text_from_tldr(
    summary: Optional[EvaluationTldrSummary],
) -> Optional[str]:
    if summary is None:
        return None
    narrative = _clamp_prose_to_sentences(summary.narrative.strip())
    return narrative or None


def _metric_insights_from_tldr(
    summary: Optional[EvaluationTldrSummary],
) -> dict[str, str]:
    if summary is None:
        return {}
    return {
        str(metric_id): insight.strip()
        for metric_id, insight in summary.metric_insights.items()
        if str(metric_id).strip() and insight.strip()
    }


def _report_period_from_rows(
    rows: list[tuple[CallImportEvaluationRow, CallImportRow]],
) -> tuple[Optional[date], Optional[date], Optional[str], str]:
    dates = [
        source_row.recording_date
        for eval_row, source_row in rows
        if eval_row.status == "completed" and source_row.recording_date
    ]
    if not dates:
        return None, None, None, "Not specified"
    start = min(dates)
    end = max(dates)
    week_anchor = max(dates)
    week_start = week_anchor - timedelta(days=week_anchor.weekday())
    week_end = week_start + timedelta(days=6)
    iso_year, iso_week, _ = week_anchor.isocalendar()
    label = f"{iso_year}-W{iso_week:02d}"
    if week_start.year == week_end.year:
        week_range = f"{week_start.strftime('%b %d')}ΓÇô{week_end.strftime('%b %d, %Y')}"
    else:
        week_range = (
            f"{week_start.strftime('%b %d, %Y')}ΓÇô{week_end.strftime('%b %d, %Y')}"
        )
    display = f"W{iso_week:02d} · {week_range}"
    return start, end, label, display


def _aggregate_to_dict(aggregate: CallImportMetricAggregate) -> dict[str, Any]:
    if hasattr(aggregate, "model_dump"):
        return aggregate.model_dump(mode="json")
    return aggregate.dict()


def _aggregate_primary_percent(
    raw: dict[str, Any],
    policy: Optional[MetricFailurePolicy] = None,
) -> Optional[float]:
    return aggregate_primary_percent(raw, policy)


def _child_names_by_parent(
    db: Session,
    organization_id: UUID,
    parent_metric_ids: Sequence[UUID],
) -> Dict[str, List[str]]:
    if not parent_metric_ids:
        return {}
    children = (
        db.query(Metric)
        .filter(
            Metric.organization_id == organization_id,
            Metric.parent_metric_id.in_(list(parent_metric_ids)),
        )
        .all()
    )
    out: Dict[str, List[str]] = {}
    for child in children:
        pid = str(child.parent_metric_id)
        out.setdefault(pid, []).append(child.name)
    return out


def _clustering_context(
    db: Session,
    evaluation: CallImportEvaluation,
    eval_rows: List[CallImportEvaluationRow],
) -> Tuple[
    List[Metric],
    List[CallImportMetricAggregate],
    Dict[str, MetricFailurePolicy],
    Literal["inferred", "user"],
    Dict[str, List[str]],
]:
    from app.api.v1.routes.call_import_evaluations.clusters import (
        _metrics_for_clustering,
    )

    metrics = _metrics_for_clustering(db, evaluation, eval_rows)
    aggregates = _compute_metric_aggregates(db, evaluation, eval_rows)
    parent_ids = [
        m.id
        for m in metrics
        if getattr(m, "selection_mode", None) and not getattr(m, "parent_metric_id", None)
    ]
    child_names_by_parent = _child_names_by_parent(
        db, evaluation.organization_id, parent_ids
    )
    policies, source = effective_policies(
        evaluation,
        metrics,
        aggregates,
        child_names_by_parent=child_names_by_parent,
    )
    return metrics, aggregates, policies, source, child_names_by_parent


def _period_deltas_from_aggregates(
    previous_metric_aggregates: list[dict[str, Any]],
    current_metric_aggregates: list[dict[str, Any]],
    policies: Optional[Dict[str, MetricFailurePolicy]] = None,
) -> dict[str, dict[str, str]]:
    current_by_id = {str(item.get("metric_id")): item for item in current_metric_aggregates}
    previous_by_id = {
        str(item.get("metric_id")): item
        for item in previous_metric_aggregates
        if isinstance(item, dict)
    }
    deltas: dict[str, dict[str, str]] = {}
    for metric_id, current in current_by_id.items():
        previous_raw = previous_by_id.get(metric_id)
        policy = (policies or {}).get(metric_id)
        current_pct = _aggregate_primary_percent(current, policy)
        previous_pct = (
            _aggregate_primary_percent(previous_raw, policy)
            if previous_raw
            else None
        )
        if current_pct is None or previous_pct is None:
            deltas[metric_id] = {
                "label": "No previous-week baseline",
                "detail": "No comparable prior report snapshot was found.",
            }
            continue
        delta = current_pct - previous_pct
        sign = "+" if delta >= 0 else ""
        deltas[metric_id] = {
            "label": f"{sign}{delta:.1f} pp",
            "detail": f"Current report {current_pct:.1f}% vs previous report {previous_pct:.1f}%",
        }
    return deltas


def _period_deltas_from_snapshot(
    previous: Optional[CallImportEvaluationReportSnapshot],
    current_metric_aggregates: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    previous_items = (
        previous.metric_aggregates
        if previous and isinstance(previous.metric_aggregates, list)
        else []
    )
    return _period_deltas_from_aggregates(previous_items, current_metric_aggregates)


# ---------------------------------------------------------------------------
# Aggregation: turns per-row metric scores into histograms / value counts.
#
# Designed to be cheap enough to call on every page load: we read each
# evaluation row once, bucket numeric values into a fixed 10-bin
# histogram, and tally the top categorical values. Scaling concerns
# (millions of rows) are deferred — at that point we'd push this into a
# Postgres aggregate query, but for typical CSV imports (<10k rows) the
# Python pass is fast enough and dramatically simpler.
# ---------------------------------------------------------------------------


_HISTOGRAM_BUCKETS = 10
_TOP_VALUE_COUNTS = 10


def _coerce_numeric(value: Any) -> Optional[float]:
    """Return ``value`` as ``float`` when it's numeric; ``None`` otherwise."""
    if isinstance(value, bool):
        # Booleans are ints in Python; treat them as categorical so
        # pass/fail metrics show up in value_counts instead of becoming
        # a degenerate {0,1} histogram.
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        try:
            f = float(value)
            if math.isfinite(f):
                return f
        except ValueError:
            return None
    return None


def _coerce_category(value: Any) -> Optional[str]:
    """Render ``value`` as a label suitable for a value_counts bucket."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    # Lists / dicts: stringify so they still group sensibly without
    # exploding the cardinality (worst case: everything is "[…]" once).
    return str(value)


def _build_histogram(
    values: List[float],
) -> List[CallImportMetricHistogramBucket]:
    """Fixed-bin histogram over ``values``; returns [] for <2 values."""
    if len(values) < 2:
        return []
    lo = min(values)
    hi = max(values)
    if lo == hi:
        # All values identical — render a single bucket so the UI shows a
        # spike rather than empty space.
        return [
            CallImportMetricHistogramBucket(x0=lo, x1=hi, count=len(values))
        ]
    width = (hi - lo) / _HISTOGRAM_BUCKETS
    buckets: List[List[float]] = [[] for _ in range(_HISTOGRAM_BUCKETS)]
    for v in values:
        # Right-edge inclusive on the last bucket so ``hi`` doesn't fall
        # off into a non-existent bucket index.
        idx = int((v - lo) / width)
        if idx >= _HISTOGRAM_BUCKETS:
            idx = _HISTOGRAM_BUCKETS - 1
        buckets[idx].append(v)
    return [
        CallImportMetricHistogramBucket(
            x0=lo + i * width,
            x1=lo + (i + 1) * width,
            count=len(bucket),
        )
        for i, bucket in enumerate(buckets)
    ]


def _percentile(values: List[float], pct: float) -> Optional[float]:
    """Linear-interpolated percentile compatible with NumPy default."""
    if not values:
        return None
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return sorted_vals[lo]
    frac = rank - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _compute_metric_aggregates(
    db: Session,
    evaluation: CallImportEvaluation,
    eval_rows: List[CallImportEvaluationRow],
) -> List[CallImportMetricAggregate]:
    """Collapse per-row ``metric_scores`` into one aggregate per metric.

    Selected metrics are read fresh from the DB so the response always
    surfaces the current ``metric.name`` / ``metric_type`` even when a
    metric was renamed after the run finished.
    """

    selected_ids = _serialize_selected_metric_ids(evaluation.selected_metric_ids)
    # Include parent metrics from selected_metric_groups so they appear
    # alongside their children in the aggregate response. Use ``getattr``
    # with a default so the helper still works for callers that pass
    # lightweight objects (tests, in-memory shims) that don't carry the
    # attribute at all.
    groups_raw_candidate = getattr(evaluation, "selected_metric_groups", None)
    groups_raw = (
        groups_raw_candidate if isinstance(groups_raw_candidate, dict) else {}
    )
    for parent_str in groups_raw.keys():
        try:
            pid = UUID(parent_str)
            if pid not in selected_ids:
                selected_ids.append(pid)
        except (TypeError, ValueError):
            continue

    from app.api.v1.routes import call_import_evaluations as eval_routes

    metrics = eval_routes._metrics_for_ids(db, evaluation.organization_id, selected_ids)
    metric_meta: Dict[str, Metric] = {str(m.id): m for m in metrics}

    # Default to selected metrics, but also include any metric ids that
    # surface in row scores even if missing from the metric registry —
    # otherwise renaming/deleting a metric mid-run would silently drop
    # results from the chart.
    discovered_ids: List[str] = list(metric_meta.keys())
    for row in eval_rows:
        scores = row.metric_scores if isinstance(row.metric_scores, dict) else {}
        for metric_id_str in scores.keys():
            if metric_id_str not in metric_meta and metric_id_str not in discovered_ids:
                discovered_ids.append(metric_id_str)

    results: List[CallImportMetricAggregate] = []

    for metric_id_str in discovered_ids:
        meta = metric_meta.get(metric_id_str)
        numeric_values: List[float] = []
        category_counts: Dict[str, int] = {}
        classification_yes_no_counts: Dict[str, int] = {}
        classification_choice_counts: Dict[str, int] = {}
        classification_level_counts: Dict[str, int] = {}
        classification_rows_scored = 0
        is_classification_metric_agg = bool(
            meta and is_classification_metric(custom_data_type=getattr(meta, "custom_data_type", None))
        )
        # For multi-label parents we still need to know how many rows
        # were scored (each row votes for >=1 label) so the n-badge in
        # the UI shows "n=50" instead of the misleading "n=208" sum.
        multi_label_rows_scored = 0
        # Unordered pair tally for the co-occurrence heatmap. Keys are
        # ``(label_a, label_b)`` with ``a < b`` so we never double-count
        # the same unordered pair. Only populated for multi-label
        # parents — every other metric leaves this empty.
        multi_label_pair_counts: Dict[Tuple[str, str], int] = {}
        skipped = 0
        errored = 0
        observed_metric_type: Optional[str] = None
        observed_name: Optional[str] = None

        # ``meta`` is a real ``Metric`` row in production, but tests
        # frequently pass a lightweight stub. Pull the two attributes
        # we need via ``getattr`` so a stub that only sets ``id`` /
        # ``name`` / ``metric_type`` doesn't blow up here.
        is_multi_label_parent = bool(
            meta
            and getattr(meta, "selection_mode", None) == "multi_label"
            and not getattr(meta, "parent_metric_id", None)
        )

        for row in eval_rows:
            scores = (
                row.metric_scores
                if isinstance(row.metric_scores, dict)
                else {}
            )
            entry = scores.get(metric_id_str)
            if not isinstance(entry, dict):
                continue
            if entry.get("metric_name"):
                observed_name = entry.get("metric_name")
            if entry.get("type"):
                observed_metric_type = entry.get("type")
            if entry.get("type") == "classification":
                is_classification_metric_agg = True
            if entry.get("skipped"):
                skipped += 1
                continue
            if entry.get("error"):
                errored += 1
                continue

            # Multi-label parents store a comma-joined value that
            # isn't useful as a single category; instead tally each
            # selected child individually so the chart shows per-label
            # counts that mirror the children's own boolean histograms.
            if is_multi_label_parent:
                selected = entry.get("selected_child_names")
                if isinstance(selected, list) and selected:
                    multi_label_rows_scored += 1
                    cleaned: List[str] = []
                    for label in selected:
                        text_label = str(label).strip() or None
                        if text_label:
                            cleaned.append(text_label)
                            category_counts[text_label] = (
                                category_counts.get(text_label, 0) + 1
                            )
                    # Emit one increment per unordered pair of distinct
                    # labels that fired together on this row. ``cleaned``
                    # is deduplicated first because the LLM occasionally
                    # repeats a label inside ``selected_child_names``.
                    distinct = sorted(set(cleaned))
                    for i in range(len(distinct)):
                        for j in range(i + 1, len(distinct)):
                            pair = (distinct[i], distinct[j])
                            multi_label_pair_counts[pair] = (
                                multi_label_pair_counts.get(pair, 0) + 1
                            )
                    continue

            if is_classification_metric_agg or entry.get("type") == "classification":
                facets = classification_facets_from_entry(entry)
                scored_classification = False
                yn = facets.get("yes_no")
                if yn:
                    classification_yes_no_counts[yn] = (
                        classification_yes_no_counts.get(yn, 0) + 1
                    )
                    scored_classification = True
                ch = facets.get("choice")
                if ch:
                    classification_choice_counts[ch] = (
                        classification_choice_counts.get(ch, 0) + 1
                    )
                    scored_classification = True
                lv = facets.get("level")
                if lv:
                    classification_level_counts[lv] = (
                        classification_level_counts.get(lv, 0) + 1
                    )
                    scored_classification = True
                if scored_classification:
                    classification_rows_scored += 1
                    continue

            value = entry.get("value")
            numeric = _coerce_numeric(value)
            if numeric is not None:
                numeric_values.append(numeric)
                continue
            category = _coerce_category(value)
            if category is not None:
                category_counts[category] = category_counts.get(category, 0) + 1

        # ``count`` is "rows scored". For numeric / single-choice
        # metrics that's the same as ``len(numeric) + sum(categories)``
        # because each scored row contributes exactly one observation.
        # Multi-label parents however contribute one observation per
        # selected child, so summing ``category_counts`` over-counts —
        # we tracked rows-scored separately above and use it here.
        legacy_rows_scored = len(numeric_values) + sum(category_counts.values())
        # Mixed migrations may score some rows via classification facets and
        # others via legacy numeric/category values for the same metric id.
        rows_scored = (
            multi_label_rows_scored
            if is_multi_label_parent
            else (classification_rows_scored + legacy_rows_scored)
            if is_classification_metric_agg
            else legacy_rows_scored
        )

        # Build numeric stats first, then categorical (both can coexist).
        agg = CallImportMetricAggregate(
            metric_id=metric_id_str,
            metric_name=(
                (meta.name if meta else observed_name) or "Unknown metric"
            ),
            metric_type=(
                meta.metric_type if meta else observed_metric_type
            ),
            metric_category=(
                "user_insight"
                if meta is not None and _metric_is_user_insight(meta)
                else "quality"
            )
            or "quality",
            is_multi_label_parent=is_multi_label_parent,
            count=rows_scored,
            skipped_count=skipped,
            error_count=errored,
        )
        if numeric_values:
            agg.mean = float(statistics.fmean(numeric_values))
            agg.median = float(statistics.median(numeric_values))
            agg.min = min(numeric_values)
            agg.max = max(numeric_values)
            agg.stddev = (
                float(statistics.pstdev(numeric_values))
                if len(numeric_values) > 1
                else 0.0
            )
            agg.p25 = _percentile(numeric_values, 25)
            agg.p75 = _percentile(numeric_values, 75)
            agg.p95 = _percentile(numeric_values, 95)
            agg.histogram_buckets = _build_histogram(numeric_values)
        if (
            is_classification_metric_agg
            and (
                classification_yes_no_counts
                or classification_choice_counts
                or classification_level_counts
            )
        ):
            def _facet_value_counts(counts: Dict[str, int]) -> List[CallImportMetricValueCount]:
                sorted_counts = sorted(
                    counts.items(), key=lambda kv: kv[1], reverse=True
                )
                return [
                    CallImportMetricValueCount(label=label, count=count)
                    for label, count in sorted_counts[:_TOP_VALUE_COUNTS]
                ]

            agg.classification_facets = CallImportClassificationFacetCounts(
                yes_no=_facet_value_counts(classification_yes_no_counts),
                choice=_facet_value_counts(classification_choice_counts),
                level=_facet_value_counts(classification_level_counts),
            )
        if category_counts:
            sorted_counts = sorted(
                category_counts.items(), key=lambda kv: kv[1], reverse=True
            )
            agg.value_counts = [
                CallImportMetricValueCount(label=label, count=count)
                for label, count in sorted_counts[:_TOP_VALUE_COUNTS]
            ]
            # Restrict the heatmap to pairs of labels we actually
            # rendered above so the frontend never has to match
            # against truncated/missing rows. Sorted desc by pair
            # count to keep the most informative cells in the
            # response when ``_TOP_VALUE_COUNTS`` clipped the matrix.
            if is_multi_label_parent and multi_label_pair_counts:
                kept_labels = {
                    label for label, _ in sorted_counts[:_TOP_VALUE_COUNTS]
                }
                pair_items = [
                    (a, b, count)
                    for (a, b), count in multi_label_pair_counts.items()
                    if a in kept_labels and b in kept_labels
                ]
                pair_items.sort(key=lambda t: t[2], reverse=True)
                agg.co_occurrence = [
                    CallImportMetricLabelPair(a=a, b=b, count=count)
                    for a, b, count in pair_items
                ]

        results.append(agg)

    # Sort so each parent metric immediately precedes its children.
    # The Visualizations grid renders metrics top-to-bottom in this
    # order, so multi-label parents (the "summary" chart) sit above
    # the per-child boolean histograms that drill into them. Metrics
    # whose ``meta`` row was deleted mid-run (``meta is None``) sink
    # to the bottom but keep their relative order.
    enumerated = list(enumerate(results))

    def _sort_key(item: Tuple[int, CallImportMetricAggregate]):
        original_idx, agg = item
        meta = metric_meta.get(agg.metric_id)
        if meta is None:
            return (1, "", 1, "", original_idx)
        parent_id = getattr(meta, "parent_metric_id", None)
        # Group key: a child shares its parent's UUID; a parent
        # uses its own UUID. Within a group, depth=0 (parent) sorts
        # before depth=1 (child); ties break alphabetically by name
        # so children render in a stable order regardless of which
        # row scored which label first.
        if parent_id is None:
            group_key = str(meta.id)
            depth = 0
        else:
            group_key = str(parent_id)
            depth = 1
        return (
            0,
            group_key,
            depth,
            (getattr(meta, "name", "") or "").lower(),
            original_idx,
        )

    enumerated.sort(key=_sort_key)
    return [agg for _idx, agg in enumerated]


@router.get(
    "/{eval_id}/aggregate",
    response_model=CallImportEvaluationAggregateResponse,
    operation_id="getCallImportEvaluationAggregate",
)
async def get_call_import_evaluation_aggregate(
    call_import_id: UUID,
    eval_id: UUID,
    baseline_evaluation_id: Optional[UUID] = Query(None),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationAggregateResponse:
    """Return per-metric distributions for the Visualizations tab.

    The shape is intentionally chart-friendly: histograms for numeric
    metrics, top-N value counts for categorical/text metrics, plus
    summary stats (mean/p50/p95) so the UI can render summary cards
    without recomputing on the client.
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

    from app.services.call_imports.metric_aggregate_cache import (
        metrics_for_aggregate_endpoint,
    )

    metrics = metrics_for_aggregate_endpoint(db, evaluation)

    period_deltas: dict[str, MetricPeriodDelta] = {}
    resolved_baseline_id: Optional[UUID] = None
    if baseline_evaluation_id is not None:
        call_import = _require_import(db, call_import_id, organization_id)
        from app.db_sharding.scatter_gather import load_evaluation_row_pairs

        rows = load_evaluation_row_pairs(db, eval_id)
        eval_rows = [eval_row for eval_row, _source_row in rows]
        period_start, _, _, _ = _report_period_from_rows(rows)
        baseline_evaluation = _resolve_baseline_evaluation(
            db,
            organization_id,
            call_import.workspace_id,
            evaluation,
            period_start,
            str(baseline_evaluation_id),
        )
        if baseline_evaluation:
            resolved_baseline_id = baseline_evaluation.id
            metric_aggregates_dicts = [
                _aggregate_to_dict(agg) for agg in metrics
            ]
            raw_deltas = _period_deltas_from_evaluation(
                db,
                baseline_evaluation,
                metric_aggregates_dicts,
                evaluation,
                eval_rows,
            )
            raw_deltas = _period_deltas_with_explanations(
                db,
                organization_id,
                evaluation,
                baseline_evaluation,
                raw_deltas,
            )
            period_deltas = {
                metric_id: MetricPeriodDelta(
                    label=delta.get("label") or "",
                    detail=delta.get("detail") or "",
                    why=(delta.get("why") or "").strip() or None,
                )
                for metric_id, delta in raw_deltas.items()
            }

    _fp_stored, failure_policies_source = policies_from_evaluation_raw(
        evaluation.metric_clusters
    )
    return CallImportEvaluationAggregateResponse(
        evaluation_id=eval_id,
        total_rows=evaluation.total_rows,
        completed_rows=evaluation.completed_rows,
        failed_rows=evaluation.failed_rows,
        metrics=metrics,
        period_deltas=period_deltas,
        baseline_evaluation_id=resolved_baseline_id,
        failure_policies_source=failure_policies_source,
    )

