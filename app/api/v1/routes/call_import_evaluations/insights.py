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
    _count_completed_eval_rows,
    _load_eval_rows,
    _metrics_for_ids,
    _require_import,
    _serialize_selected_metric_ids,
)
from app.api.v1.routes.call_import_evaluations.aggregate import (  # noqa: E402
    _clamp_prose_to_sentences,
    _compute_metric_aggregates,
)

# TLDR insights: LLM-generated narrative + bullet patterns rendered above
# the Visualizations charts. Cached on ``CallImportEvaluation.tldr_summary``
# so the page never auto-burns LLM tokens; the user explicitly clicks
# "Generate summary" or "Regenerate" from the empty-state CTA.
# ---------------------------------------------------------------------------


_INSIGHTS_SYSTEM_PROMPT = (
    "You are a senior conversation-analytics reviewer. You will be "
    "given aggregated metric statistics + a sample of rationales for "
    "the rows of a single call-import evaluation. Identify the most "
    "useful PATTERNS that hold ACROSS the calls -- not just per-metric "
    "numbers. Look for combinations (e.g. `when X happens, Y also "
    "tends to happen`), notable outliers, frequent failure modes, and "
    "any signal that would change how a reviewer triages the run.\n\n"
    "Return STRICT JSON only, with this shape and no extra keys:\n"
    "{\n"
    '  "narrative": "<max 3 short sentences, <=300 chars total>",\n'
    '  "patterns": ["<bullet 1>", "<bullet 2>", ...],\n'
    '  "metric_insights": {"<metric_id>": "<2-3 line business meaning>"}\n'
    "}\n\n"
    "Constraints:\n"
    "- narrative is the ONLY text shown in the external audit summary and "
    "Visualizations TLDR; keep it to at most 3 short sentences (~300 chars).\n"
    "- patterns are optional supporting notes and are NOT rendered in the "
    "audit summary; keep 0 to 3 bullets if supplied, each <= 120 characters.\n"
    "- metric_insights must include one entry for each top-level metric id supplied.\n"
    "- Each metric insight should explain what the metric means for the business and what the current distribution suggests, not restate the metric rubric.\n"
    "- Avoid restating raw counts unless they reveal a pattern.\n"
    "- Use neutral, factual language ('frustration appeared in...') "
    "rather than judgemental ('the agents failed to...')."
)


def _tldr_summary_payload(
    evaluation: CallImportEvaluation,
) -> Optional[EvaluationTldrSummary]:
    """Return the cached TLDR (with ``is_stale`` set) or ``None``.

    ``CallImportEvaluation.tldr_summary`` is a ``JSON`` column so we
    have to validate shape defensively -- a half-written or hand-edited
    blob should not break the aggregate response. Returns ``None`` when
    no cached summary exists.
    """
    raw = evaluation.tldr_summary
    if not isinstance(raw, dict):
        return None
    narrative = raw.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        return None
    patterns_raw = raw.get("patterns")
    patterns = (
        [str(p) for p in patterns_raw if isinstance(p, str) and p.strip()]
        if isinstance(patterns_raw, list)
        else []
    )
    metric_insights_raw = raw.get("metric_insights")
    metric_insights = (
        {
            str(metric_id): str(insight).strip()
            for metric_id, insight in metric_insights_raw.items()
            if str(metric_id).strip()
            and isinstance(insight, str)
            and insight.strip()
        }
        if isinstance(metric_insights_raw, dict)
        else {}
    )
    generated_at_raw = raw.get("generated_at")
    try:
        generated_at = (
            datetime.fromisoformat(generated_at_raw)
            if isinstance(generated_at_raw, str)
            else evaluation.updated_at or datetime.now(timezone.utc)
        )
    except ValueError:
        generated_at = evaluation.updated_at or datetime.now(timezone.utc)
    snapshot = raw.get("generated_at_completed_rows")
    snapshot_int = int(snapshot) if isinstance(snapshot, (int, float)) else 0
    return EvaluationTldrSummary(
        narrative=_clamp_prose_to_sentences(narrative.strip()),
        patterns=patterns,
        metric_insights=metric_insights,
        generated_at=generated_at,
        generated_at_completed_rows=snapshot_int,
        provider=raw.get("provider") if isinstance(raw.get("provider"), str) else None,
        model=raw.get("model") if isinstance(raw.get("model"), str) else None,
        is_stale=evaluation.completed_rows > snapshot_int,
    )


def _sample_rationales_per_metric(
    eval_rows: List[CallImportEvaluationRow],
    *,
    per_metric_cap: int = 3,
    rationale_char_cap: int = 600,
) -> Dict[str, List[str]]:
    """Collect up to ``per_metric_cap`` distinct rationales per metric.

    Distinctness is case- and whitespace-insensitive. We truncate each
    rationale to ``rationale_char_cap`` so a few unusually verbose rows
    can't dominate the prompt budget. Empty / non-string rationales are
    skipped.
    """
    out: Dict[str, List[str]] = {}
    seen: Dict[str, set[str]] = {}
    for row in eval_rows:
        scores = row.metric_scores if isinstance(row.metric_scores, dict) else {}
        for metric_id, entry in scores.items():
            if not isinstance(entry, dict):
                continue
            rationale = entry.get("rationale")
            if not isinstance(rationale, str):
                continue
            text = rationale.strip()
            if not text:
                continue
            bucket = out.setdefault(metric_id, [])
            if len(bucket) >= per_metric_cap:
                continue
            key = " ".join(text.lower().split())
            seen_set = seen.setdefault(metric_id, set())
            if key in seen_set:
                continue
            seen_set.add(key)
            bucket.append(text[:rationale_char_cap])
    return out


def _build_insights_messages(
    evaluation: CallImportEvaluation,
    aggregate: List[CallImportMetricAggregate],
    rationale_samples: Dict[str, List[str]],
    metric_meta: Dict[str, Metric],
) -> List[Dict[str, str]]:
    """Render the user prompt fed to the LLM.

    The shape is plain markdown-ish text instead of JSON so the LLM can
    skim it without us spending tokens on verbose schema delimiters.
    Parent metrics surface their child metrics nested underneath so the
    model sees the hierarchy and can talk about "X often co-occurred
    with Y" rather than treating sub-labels as standalone metrics.
    """
    name = evaluation.name or f"Run {str(evaluation.id)[:8]}"
    lines: List[str] = [
        f"Evaluation: {name}",
        (
            f"Rows: total={evaluation.total_rows} "
            f"completed={evaluation.completed_rows} "
            f"failed={evaluation.failed_rows}"
        ),
        "",
        "## Per-metric aggregate",
    ]

    # Group metrics by parent so the prompt mirrors the hierarchy. Any
    # aggregate row whose ``metric_id`` is missing from ``metric_meta``
    # is rendered as a leaf at the top-level list (handles renamed /
    # deleted parents).
    children_by_parent: Dict[str, List[CallImportMetricAggregate]] = {}
    top_level: List[CallImportMetricAggregate] = []
    for agg in aggregate:
        meta = metric_meta.get(agg.metric_id)
        parent_id = (
            str(meta.parent_metric_id)
            if meta is not None and getattr(meta, "parent_metric_id", None)
            else None
        )
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(agg)
        else:
            top_level.append(agg)

    def _format_metric_block(agg: CallImportMetricAggregate, indent: int) -> List[str]:
        prefix = "  " * indent + "- "
        bits: List[str] = [f"{prefix}{agg.metric_name} [id={agg.metric_id}] (n={agg.count}"]
        if agg.skipped_count:
            bits.append(f", skipped={agg.skipped_count}")
        if agg.error_count:
            bits.append(f", errors={agg.error_count}")
        bits.append(")")
        meta = metric_meta.get(agg.metric_id)
        description = (meta.description or "").strip() if meta else ""
        if description:
            bits.append(f" | definition={description[:500]}")
        if agg.mean is not None:
            mean_s = f"{agg.mean:.2f}"
            stddev_s = f"{agg.stddev:.2f}" if agg.stddev is not None else "-"
            bits.append(f" | mean={mean_s} stddev={stddev_s}")
            if agg.min is not None and agg.max is not None:
                bits.append(f" range=[{agg.min:.2f}, {agg.max:.2f}]")
        if agg.value_counts:
            total = sum(v.count for v in agg.value_counts) or 1
            top = agg.value_counts[:3]
            shares = ", ".join(
                f'"{v.label}"={v.count}/{total}' for v in top
            )
            bits.append(f" | top={shares}")
        result = ["".join(bits)]
        rationales = rationale_samples.get(agg.metric_id, [])
        for r in rationales:
            result.append("  " * (indent + 1) + f"- rationale: {r}")
        return result

    for agg in top_level:
        lines.extend(_format_metric_block(agg, indent=0))
        meta = metric_meta.get(agg.metric_id)
        children = children_by_parent.get(str(meta.id), []) if meta else []
        for child in children:
            lines.extend(_format_metric_block(child, indent=1))

    lines.append("")
    top_level_ids = [agg.metric_id for agg in top_level]
    if top_level_ids:
        lines.append(
            "metric_insights keys must exactly use these top-level metric ids: "
            + ", ".join(top_level_ids)
        )
        lines.append("")
    lines.append(
        "Write the JSON object as instructed. Do not include "
        "preamble, code fences, or trailing commentary."
    )

    return [
        {"role": "system", "content": _INSIGHTS_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _parse_insights_response(text: str) -> EvaluationTldrSummary:
    """Coerce the LLM response into ``narrative`` + ``patterns``.

    Matches the JSON-with-fallback pattern used by
    ``app.api.v1.routes.metrics._parse_metric_generation_response``: try
    ``json.loads`` first, then fall back to regex extraction of the
    first ``{...}`` block. Raises ``HTTPException`` with a 502 when the
    response can't be parsed at all.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=502, detail="LLM returned an empty insights response"
        )
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        import re

        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise HTTPException(
                status_code=502,
                detail="Could not parse LLM insights response as JSON",
            )
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Could not parse LLM insights response: {e}",
            )

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=502, detail="LLM insights JSON was not an object"
        )

    narrative = parsed.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        raise HTTPException(
            status_code=502,
            detail="LLM insights JSON missing 'narrative' string",
        )

    patterns_raw = parsed.get("patterns")
    if patterns_raw is None:
        patterns: List[str] = []
    elif isinstance(patterns_raw, list):
        patterns = [
            str(p).strip()
            for p in patterns_raw
            if isinstance(p, str) and p.strip()
        ]
    else:
        raise HTTPException(
            status_code=502,
            detail="LLM insights JSON 'patterns' must be a list of strings",
        )
    metric_insights_raw = parsed.get("metric_insights")
    if metric_insights_raw is None:
        metric_insights: Dict[str, str] = {}
    elif isinstance(metric_insights_raw, dict):
        metric_insights = {
            str(metric_id): str(insight).strip()
            for metric_id, insight in metric_insights_raw.items()
            if str(metric_id).strip()
            and isinstance(insight, str)
            and insight.strip()
        }
    else:
        raise HTTPException(
            status_code=502,
            detail="LLM insights JSON 'metric_insights' must be an object",
        )

    return EvaluationTldrSummary(
        narrative=_clamp_prose_to_sentences(narrative.strip()),
        patterns=patterns,
        metric_insights=metric_insights,
        generated_at=datetime.now(timezone.utc),
        generated_at_completed_rows=0,  # filled in by caller
        is_stale=False,
    )


def _generate_and_persist_tldr_summary(
    db: Session,
    evaluation: CallImportEvaluation,
    *,
    organization_id: UUID,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> EvaluationTldrSummary:
    """LLM TLDR generation used by the imports-queue Celery worker."""
    eval_id = evaluation.id
    from app.db_sharding.scatter_gather import (
        INSIGHTS_TLDR_ROW_SAMPLE,
        load_completed_evaluation_row_pairs_sample,
    )
    from app.services.call_imports.metric_aggregate_cache import (
        evaluation_metric_aggregates_for_analysis,
    )

    aggregate = evaluation_metric_aggregates_for_analysis(db, evaluation)
    if not aggregate:
        raise HTTPException(
            status_code=400,
            detail=(
                "No metric data yet. Wait for at least one row to "
                "finish scoring before generating a summary."
            ),
        )

    metric_ids: List[UUID] = []
    for agg in aggregate:
        try:
            metric_ids.append(UUID(agg.metric_id))
        except (TypeError, ValueError):
            continue
    metrics = _metrics_for_ids(db, organization_id, metric_ids)
    metric_meta: Dict[str, Metric] = {str(m.id): m for m in metrics}

    rationale_samples = _sample_rationales_per_metric(
        [eval_row for eval_row, _ in load_completed_evaluation_row_pairs_sample(
            db, eval_id, max_pairs=INSIGHTS_TLDR_ROW_SAMPLE
        )]
    )
    messages = _build_insights_messages(
        evaluation, aggregate, rationale_samples, metric_meta
    )

    from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request
    from app.services.ai.llm_service import llm_service
    from app.services.usage.call_import_context import (
        call_import_evaluation_usage_context,
    )
    from app.services.usage.context import llm_usage_context

    provider_enum, model_str = get_llm_provider_and_model_for_request(
        organization_id, db, provider, model
    )

    try:
        with llm_usage_context(
            call_import_evaluation_usage_context(
                organization_id=organization_id,
                workspace_id=evaluation.workspace_id,
                evaluation_id=evaluation.id,
                call_import_id=evaluation.call_import_id,
            )
        ):
            llm_result = llm_service.generate_response(
                messages=messages,
                llm_provider=provider_enum,
                llm_model=model_str,
                organization_id=organization_id,
                db=db,
                temperature=0.4,
                max_tokens=4096,
            )
            if llm_result.get("truncated"):
                llm_result = llm_service.generate_response(
                    messages=messages,
                    llm_provider=provider_enum,
                    llm_model=model_str,
                    organization_id=organization_id,
                    db=db,
                    temperature=0.2,
                    max_tokens=8192,
                )
    except Exception as e:
        logger.error(f"[CallImportInsights] LLM call failed: {e}")
        raise HTTPException(
            status_code=502, detail=f"LLM call failed: {e}"
        ) from e

    if llm_result.get("truncated"):
        raise HTTPException(
            status_code=502,
            detail="Insights response was cut off before it finished. Try again.",
        )

    total = int(evaluation.total_rows or 0)
    summary = _parse_insights_response(llm_result.get("text", ""))
    ui_completed = min(int(evaluation.completed_rows or 0), total) if total else int(
        evaluation.completed_rows or 0
    )
    summary.generated_at_completed_rows = ui_completed
    summary.provider = provider_enum.value
    summary.model = model_str
    summary.is_stale = False

    evaluation.tldr_summary = {
        "narrative": summary.narrative,
        "patterns": summary.patterns,
        "metric_insights": summary.metric_insights,
        "generated_at": summary.generated_at.isoformat(),
        "generated_at_completed_rows": summary.generated_at_completed_rows,
        "provider": summary.provider,
        "model": summary.model,
    }
    flag_modified(evaluation, "tldr_summary")
    db.commit()
    db.refresh(evaluation)
    return summary


@router.get(
    "/{eval_id}/insights",
    response_model=Optional[EvaluationTldrSummary],
    operation_id="getCallImportEvaluationInsights",
)
async def get_call_import_evaluation_insights(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Optional[EvaluationTldrSummary]:
    """Return the cached TLDR (or ``null``) without contacting the LLM.

    Used by the Visualizations tab on first paint so the empty-state
    CTA can show up before the user opts into generation.
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
    return _tldr_summary_payload(evaluation)


@router.post(
    "/{eval_id}/insights",
    response_model=EvaluationTldrSummary,
    operation_id="generateCallImportEvaluationInsights",
)
async def generate_call_import_evaluation_insights(
    call_import_id: UUID,
    eval_id: UUID,
    body: EvaluationInsightsRequest = Body(default_factory=EvaluationInsightsRequest),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> EvaluationTldrSummary:
    """Generate (or return-cached) the LLM TLDR for an evaluation run.

    Behavior:

    * ``body.regenerate=False`` and a cached summary at the current
      ``completed_rows`` watermark exists -> return it as-is.
    * ``body.regenerate=False`` and a stale cached summary exists
      (``generated_at_completed_rows < completed_rows``) -> return it
      with ``is_stale=True``; the UI prompts the user to regenerate.
    * Otherwise -> resolve provider+model (auto-detect when omitted),
      call the LLM, persist the new summary, return it.
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

    if not body.regenerate:
        cached = _tldr_summary_payload(evaluation)
        if cached is not None:
            return cached

    # Run the TLDR LLM on the imports worker (not the default worker or API).
    from app.workers.tasks.generate_evaluation_tldr_insights import (
        generate_evaluation_tldr_insights_task,
    )

    try:
        task_result = generate_evaluation_tldr_insights_task.apply_async(
            kwargs={
                "evaluation_id": str(eval_id),
                "call_import_id": str(call_import_id),
                "organization_id": str(organization_id),
                "provider": body.provider,
                "model": body.model,
            },
        ).get(timeout=25 * 60)
    except Exception as exc:
        logger.error(
            "[CallImportInsights] TLDR task failed for evaluation {}: {}",
            eval_id,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Summary generation failed: {exc}",
        ) from exc

    if isinstance(task_result, dict) and task_result.get("error"):
        status_code = int(task_result.get("status_code") or 502)
        raise HTTPException(
            status_code=status_code,
            detail=str(task_result["error"]),
        )

    summary = EvaluationTldrSummary.model_validate(task_result)
    db.refresh(evaluation)
    stamp_evaluation_actor(evaluation, principal)
    db.commit()
    db.refresh(evaluation)

    from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request

    provider_enum, model_str = get_llm_provider_and_model_for_request(
        organization_id, db, body.provider, body.model, body.credential_id
    )

    _enqueue_user_insights_job(
        evaluation,
        provider=summary.provider or provider_enum.value,
        model=summary.model or model_str,
        force=body.regenerate,
        max_llm_calls=body.max_llm_calls,
        db=db,
        principal=principal,
    )

    return summary


def _user_insights_payload(
    evaluation: CallImportEvaluation,
) -> Optional[EvaluationUserInsightsState]:
    raw = getattr(evaluation, "user_insights", None)
    if raw is None:
        return None
    return user_insights_state_from_raw(
        raw,
        completed_rows=evaluation.completed_rows,
    )


def _selected_generated_user_insights(
    state: Optional[EvaluationUserInsightsState],
    report_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Filter and order generated insights for PDF section 03."""
    if state is None or state.status != "completed" or not state.insights:
        return []

    selected_ids = report_config.get("user_insight_ids")
    if isinstance(selected_ids, list) and selected_ids:
        allowed = {str(item) for item in selected_ids if item}
        items = [item for item in state.insights if item.id in allowed]
    else:
        items = list(state.insights)

    order_raw = report_config.get("order")
    order_ids: list[str] = []
    if isinstance(order_raw, dict):
        user_order = order_raw.get("user_insights")
        if isinstance(user_order, list):
            order_ids = [str(item) for item in user_order if item]

    if order_ids:
        by_id = {item.id: item for item in items}
        ordered = [by_id[iid] for iid in order_ids if iid in by_id]
        seen = set(order_ids)
        ordered.extend(item for item in items if item.id not in seen)
        items = ordered

    return [item.model_dump(mode="json") for item in items]


def _enqueue_user_insights_job(
    evaluation: CallImportEvaluation,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    force: bool = False,
    max_llm_calls: Optional[int] = None,
    db: Optional[Session] = None,
    principal: Optional[Principal] = None,
) -> None:
    """Enqueue background user-insights generation unless already running."""
    current = _user_insights_payload(evaluation)
    if current is not None and current.status == "running" and not force:
        return

    llm_budget = normalize_max_llm_calls(max_llm_calls)

    completed_count = (
        _count_completed_eval_rows(db, evaluation.id)
        if db is not None
        else evaluation.completed_rows
    )
    total_calls = total_llm_calls_for_rows(completed_count, max_llm_calls=llm_budget)
    evaluation.user_insights = {
        "status": "running",
        "insights": (
            (evaluation.user_insights or {}).get("insights", [])
            if isinstance(evaluation.user_insights, dict)
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
    }
    if db is not None:
        if principal is not None:
            stamp_evaluation_actor(evaluation, principal)
        flag_modified(evaluation, "user_insights")
        db.commit()

    from app.workers.tasks.generate_evaluation_user_insights import (
        generate_evaluation_user_insights_task,
    )

    generate_evaluation_user_insights_task.delay(
        str(evaluation.id),
        provider=provider,
        model=model,
        max_llm_calls=llm_budget,
    )


@router.get(
    "/{eval_id}/user-insights",
    response_model=Optional[EvaluationUserInsightsState],
    operation_id="getCallImportEvaluationUserInsights",
)
async def get_call_import_evaluation_user_insights(
    call_import_id: UUID,
    eval_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Optional[EvaluationUserInsightsState]:
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
    return _user_insights_payload(evaluation)


@router.post(
    "/{eval_id}/user-insights",
    response_model=EvaluationUserInsightsState,
    operation_id="generateCallImportEvaluationUserInsights",
)
async def generate_call_import_evaluation_user_insights(
    call_import_id: UUID,
    eval_id: UUID,
    body: EvaluationUserInsightsRequest = Body(
        default_factory=EvaluationUserInsightsRequest
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> EvaluationUserInsightsState:
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
        cached = _user_insights_payload(evaluation)
        if cached is not None and cached.status in {"running", "completed"}:
            return cached

    eval_rows = _load_eval_rows(db, eval_id)
    if not any(row.status == "completed" for row in eval_rows):
        raise HTTPException(
            status_code=400,
            detail=(
                "No completed rows yet. Wait for at least one row to "
                "finish scoring before generating user insights."
            ),
        )

    from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request

    provider_enum, model_str = get_llm_provider_and_model_for_request(
        organization_id, db, body.provider, body.model, body.credential_id
    )

    _enqueue_user_insights_job(
        evaluation,
        provider=provider_enum.value,
        model=model_str,
        force=body.force or body.regenerate,
        max_llm_calls=body.max_llm_calls,
        db=db,
        principal=principal,
    )

    db.refresh(evaluation)
    return _user_insights_payload(evaluation) or EvaluationUserInsightsState(
        status="running"
    )

