"""Call Import evaluation PDF report API orchestration."""

from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import Principal
from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationPdfReport,
    CallImportEvaluationReportSnapshot,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    Workspace,
)
from app.services.metric_failure_policy import effective_policies
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
from app.api.v1.routes.call_import_evaluations._shared import (
    _metrics_for_ids,
    _serialize_selected_metric_ids,
)
from app.api.v1.routes.call_import_evaluations.aggregate import (
    _aggregate_to_dict,
    _audit_summary_text_from_tldr,
    _baseline_candidate_evaluations,
    _benchmark_context_for_evaluation,
    _child_names_by_parent,
    _compute_metric_aggregates,
    _evaluation_rows_for_period,
    _metric_insights_from_tldr,
    _metric_is_user_insight,
    _period_deltas_from_evaluation,
    _period_deltas_with_explanations,
    _report_period_from_rows,
    _resolve_baseline_evaluation,
)
from app.api.v1.routes.call_import_evaluations.clusters import (
    _metric_clusters_payload,
    _selected_metric_clusters_for_pdf,
)
from app.api.v1.routes.call_import_evaluations.insights import (
    _selected_generated_user_insights,
    _tldr_summary_payload,
    _user_insights_payload,
)
from app.api.v1.routes.call_import_evaluations.prompts import (
    _prompt_improvements_payload,
    _selected_prompt_improvements_for_pdf,
)

class CallImportEvaluationPdfReportRequest(BaseModel):
    vendor_name: str = Field(..., min_length=1, max_length=120)
    report_type: Literal["external", "internal"] = "external"
    include_weekly_delta: bool = False
    include_period_delta: bool = False
    baseline_evaluation_id: Optional[str] = None
    period_label: Optional[str] = Field(default=None, max_length=64)
    use_case: Optional[str] = Field(default=None, max_length=120)
    internal_brand_image_id: Optional[str] = None
    external_brand_image_id: Optional[str] = None
    report_config: Dict[str, Any] = Field(default_factory=dict)
    platform_base_url: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Frontend origin for deep links to example calls in internal PDFs.",
    )

    @field_validator("vendor_name")
    @classmethod
    def _clean_vendor_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Vendor name is required.")
        return cleaned


class CallImportEvaluationPdfReportResponse(BaseModel):
    id: str
    filename: str
    preview_url: Optional[str] = None
    download_url: Optional[str] = None
    created_at: datetime
    created_by: Optional[str] = None
    report_type: str
    vendor_name: str
    config_summary: Optional[str] = None
    storage_available: bool = True
    cache_hit: bool = False


class CallImportEvaluationPdfReportListItem(BaseModel):
    id: str
    filename: Optional[str] = None
    vendor_name: str
    report_type: str
    created_by: Optional[str] = None
    created_at: datetime
    config_summary: Optional[str] = None
    cache_fingerprint: Optional[str] = None


class CallImportEvaluationPdfReportListResponse(BaseModel):
    items: List[CallImportEvaluationPdfReportListItem]


class CallImportEvaluationBaselineCandidate(BaseModel):
    evaluation_id: str
    name: str
    dataset: str
    period_label: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    period_display: str
    completed_rows: int
    created_at: datetime
    is_default: bool = False


class CallImportEvaluationBaselineCandidatesResponse(BaseModel):
    items: List[CallImportEvaluationBaselineCandidate]
    default_evaluation_id: Optional[str] = None

def _report_filename_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "client"


def _pdf_report_actor(principal: Principal) -> tuple[Optional[str], Optional[UUID]]:
    created_by = principal.email
    if not created_by and principal.user_id:
        created_by = str(principal.user_id)
    return created_by, principal.user_id


def _pdf_report_response_from_row(
    row: CallImportEvaluationPdfReport,
    *,
    cache_hit: bool = False,
) -> CallImportEvaluationPdfReportResponse:
    filename = row.filename or "report.pdf"
    preview_url, download_url = presigned_urls_for_pdf_report(
        row.s3_key or "",
        filename,
    )
    return CallImportEvaluationPdfReportResponse(
        id=str(row.id),
        filename=filename,
        preview_url=preview_url,
        download_url=download_url,
        created_at=row.created_at or datetime.now(timezone.utc),
        created_by=row.created_by,
        report_type=row.report_type,
        vendor_name=row.vendor_name,
        config_summary=config_summary_from_report_config(
            row.report_config if isinstance(row.report_config, dict) else {}
        ),
        storage_available=bool(row.s3_key),
        cache_hit=cache_hit,
    )


def _pdf_report_list_item_from_row(
    row: CallImportEvaluationPdfReport,
) -> CallImportEvaluationPdfReportListItem:
    return CallImportEvaluationPdfReportListItem(
        id=str(row.id),
        filename=row.filename,
        vendor_name=row.vendor_name,
        report_type=row.report_type,
        created_by=row.created_by,
        created_at=row.created_at or datetime.now(timezone.utc),
        config_summary=config_summary_from_report_config(
            row.report_config if isinstance(row.report_config, dict) else {}
        ),
        cache_fingerprint=row.cache_fingerprint,
    )


def _report_branding_for_import_workspace(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    *,
    internal_brand_image_id: Optional[str] = None,
    external_brand_image_id: Optional[str] = None,
) -> tuple[dict[str, str] | list[str], Optional[str]]:
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
        )
        .first()
    )
    raw = workspace.report_branding if workspace and isinstance(workspace.report_branding, dict) else {}
    images = raw.get("images") if isinstance(raw.get("images"), list) else []
    loaded_images: list[dict[str, str]] = []
    for item in images:
        if not isinstance(item, dict) or not item.get("s3_key"):
            continue
        content_type = str(item.get("content_type") or "image/png")
        try:
            from app.services.storage.s3_service import s3_service

            image_bytes = s3_service.download_file_by_key(str(item["s3_key"]))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Unable to load report branding image for workspace {}: {}",
                workspace_id,
                exc,
            )
            continue
        encoded = base64.b64encode(image_bytes).decode("ascii")
        role = str(item.get("role") or "generic")
        if role not in {"internal", "external", "generic"}:
            role = "generic"
        loaded_images.append(
            {
                "id": str(item.get("id") or ""),
                "role": role,
                "data_uri": f"data:{content_type};base64,{encoded}",
            }
        )

    def _pick(role: str, selected_id: Optional[str]) -> Optional[str]:
        if selected_id:
            for loaded in loaded_images:
                if loaded["id"] == selected_id:
                    return loaded["data_uri"]
        for loaded in loaded_images:
            if loaded["role"] == role:
                return loaded["data_uri"]
        return None

    logo_data_uris: dict[str, str] = {}
    internal_uri = _pick("internal", internal_brand_image_id)
    external_uri = _pick("external", external_brand_image_id)
    if internal_uri:
        logo_data_uris["internal"] = internal_uri
    if external_uri:
        logo_data_uris["external"] = external_uri
    if (
        not logo_data_uris
        and not internal_brand_image_id
        and not external_brand_image_id
    ):
        # Backward compatibility for workspaces that only had a generic logo
        # library before the two-slot report header existed.
        generic_uris = [
            loaded["data_uri"]
            for loaded in loaded_images
            if loaded.get("data_uri")
        ]
        if generic_uris:
            heading = raw.get("heading") if isinstance(raw.get("heading"), str) else None
            return generic_uris[:4], heading
    heading = raw.get("heading") if isinstance(raw.get("heading"), str) else None
    return logo_data_uris, heading


def _display_metrics_for_pdf_report(
    db: Session,
    organization_id: UUID,
    evaluation: CallImportEvaluation,
) -> list[Metric]:
    selected_metric_ids = _serialize_selected_metric_ids(evaluation.selected_metric_ids)
    lookup_ids: List[UUID] = list(selected_metric_ids)
    groups_raw = (
        evaluation.selected_metric_groups
        if isinstance(evaluation.selected_metric_groups, dict)
        else {}
    )
    for parent_str in groups_raw.keys():
        try:
            parent_id = UUID(parent_str)
        except (TypeError, ValueError):
            continue
        if parent_id not in lookup_ids:
            lookup_ids.append(parent_id)

    metrics = _metrics_for_ids(db, organization_id, lookup_ids)
    child_ids_in_groups: set[str] = set()
    for child_strs in groups_raw.values():
        if not isinstance(child_strs, list):
            continue
        child_ids_in_groups.update(str(child_id) for child_id in child_strs)

    metrics_by_id = {str(metric.id): metric for metric in metrics}
    display: list[Metric] = []
    seen: set[str] = set()

    for parent_str in groups_raw.keys():
        parent = metrics_by_id.get(str(parent_str))
        if parent and str(parent.id) not in seen:
            display.append(parent)
            seen.add(str(parent.id))

    for metric in metrics:
        metric_id = str(metric.id)
        if metric_id in seen or metric_id in child_ids_in_groups:
            continue
        if metric.selection_mode and not metric.parent_metric_id:
            continue
        display.append(metric)
        seen.add(metric_id)

    return display


def _sample_evidence_for_metrics(
    rows: list[tuple[CallImportEvaluationRow, CallImportRow]],
    metric_ids: set[str],
) -> dict[str, list[dict[str, str]]]:
    samples: dict[str, list[dict[str, str]]] = {metric_id: [] for metric_id in metric_ids}
    for eval_row, source_row in rows:
        scores = eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
        for metric_id in metric_ids:
            if len(samples.get(metric_id, [])) >= 4:
                continue
            score = scores.get(metric_id)
            if not isinstance(score, dict):
                continue
            rationale = score.get("rationale")
            transcript = source_row.diarised_transcript or source_row.transcript or ""
            quote = rationale if isinstance(rationale, str) and rationale.strip() else transcript[:350]
            if quote:
                samples.setdefault(metric_id, []).append(
                    {
                        "conversation_id": source_row.conversation_id,
                        "quote": str(quote).strip()[:500],
                    }
                )
    return samples


def _fallback_report_narrative(
    insight_aggregates: list[dict[str, Any]],
    evidence_samples: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    observations: dict[str, str] = {}
    evidence: dict[str, dict[str, str]] = {}
    design_notes: list[str] = []
    for aggregate in insight_aggregates:
        metric_id = str(aggregate.get("metric_id") or "")
        name = str(aggregate.get("metric_name") or "Insight")
        counts = aggregate.get("value_counts") if isinstance(aggregate.get("value_counts"), list) else []
        if counts:
            top = counts[0]
            total = int(aggregate.get("count") or 0) or sum(
                int(item.get("count") or 0) for item in counts if isinstance(item, dict)
            )
            pct = (int(top.get("count") or 0) / total) * 100 if total else 0
            observations[metric_id] = (
                f"{top.get('label')} is the dominant {name.lower()} category at {pct:.1f}% of classified calls."
            )
            design_notes.append(
                f"{name}: {top.get('label')} is the largest segment and should be reviewed for workflow or prompt improvements."
            )
        sample = (evidence_samples.get(metric_id) or [{}])[0]
        if sample:
            evidence[metric_id] = sample
    return {
        "observations": observations,
        "evidence": evidence,
        "design_notes": design_notes[:7],
        "audit_summary": None,
    }


def _generate_report_narrative(
    db: Session,
    organization_id: UUID,
    *,
    metric_aggregates: list[dict[str, Any]],
    insight_aggregates: list[dict[str, Any]],
    period_delta_by_metric: dict[str, dict[str, str]],
    evidence_samples: dict[str, list[dict[str, str]]],
    report_config: dict[str, Any],
) -> dict[str, Any]:
    if not insight_aggregates:
        return {"observations": {}, "evidence": {}, "design_notes": [], "audit_summary": None}
    try:
        from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request
        from app.services.ai.llm_service import llm_service

        llm_provider = (report_config.get("llm_provider") or "").strip() or None
        llm_model = (report_config.get("llm_model") or "").strip() or None
        llm_credential_id = report_config.get("llm_credential_id")
        if not llm_provider and not llm_credential_id:
            return {"observations": {}, "evidence": {}, "design_notes": [], "audit_summary": None}
        provider_enum, model_str = get_llm_provider_and_model_for_request(
            organization_id,
            db,
            llm_provider,
            llm_model,
            credential_id=llm_credential_id,
        )
        prompt = (
            "You are writing a vendor-safe external call quality audit report. "
            "Return strict JSON with keys observations (object keyed by metric_id), "
            "evidence (object keyed by metric_id with conversation_id and quote), "
            "design_notes (array of concise numbered-note strings), and audit_summary (string). "
            "Use only the supplied aggregates and evidence samples.\n\n"
            + json.dumps(
                {
                    "metric_aggregates": metric_aggregates[:30],
                    "insight_aggregates": insight_aggregates,
                    "period_deltas": period_delta_by_metric,
                    "evidence_samples": evidence_samples,
                    "report_config": report_config,
                },
                default=str,
            )
        )
        llm_result = llm_service.generate_response(
            messages=[
                {"role": "system", "content": "Return JSON only. No markdown."},
                {"role": "user", "content": prompt},
            ],
            llm_provider=provider_enum,
            llm_model=model_str,
            organization_id=organization_id,
            db=db,
            temperature=0.2,
            max_tokens=1200,
        )
        parsed = json.loads(str(llm_result.content or "{}"))
        if isinstance(parsed, dict):
            fallback = _fallback_report_narrative(insight_aggregates, evidence_samples)
            return {
                "observations": parsed.get("observations") or fallback["observations"],
                "evidence": parsed.get("evidence") or fallback["evidence"],
                "design_notes": parsed.get("design_notes") or fallback["design_notes"],
                "audit_summary": parsed.get("audit_summary") or fallback["audit_summary"],
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report narrative LLM generation fell back to deterministic text: {}", exc)
    return _fallback_report_narrative(insight_aggregates, evidence_samples)

def baseline_candidates_response(
    db: Session,
    *,
    call_import: CallImport,
    evaluation: CallImportEvaluation,
    organization_id: UUID,
) -> CallImportEvaluationBaselineCandidatesResponse:
    rows = _evaluation_rows_for_period(db, evaluation.id)
    period_start, _period_end, _derived_period_label, _period_display = _report_period_from_rows(
        rows
    )
    candidates = _baseline_candidate_evaluations(
        db,
        organization_id,
        call_import.workspace_id,
        evaluation,
        period_start,
    )
    default_evaluation_id = next(
        (item["evaluation_id"] for item in candidates if item.get("is_default")),
        None,
    )
    return CallImportEvaluationBaselineCandidatesResponse(
        items=[CallImportEvaluationBaselineCandidate(**item) for item in candidates],
        default_evaluation_id=default_evaluation_id,
    )


async def generate_call_import_evaluation_pdf_report(
    db: Session,
    *,
    call_import: CallImport,
    evaluation: CallImportEvaluation,
    organization_id: UUID,
    eval_id: UUID,
    call_import_id: UUID,
    payload: CallImportEvaluationPdfReportRequest,
    principal: Principal,
):
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

    is_internal = payload.report_type == "internal"
    from app.db_sharding.scatter_gather import load_evaluation_row_pairs
    from app.db_sharding.sessions import is_sharding_enabled

    if is_sharding_enabled():
        rows = sorted(
            load_evaluation_row_pairs(db, eval_id),
            key=lambda pair: int(pair[1].row_index or 0),
        )
    else:
        rows = (
            db.query(CallImportEvaluationRow, CallImportRow)
            .join(
                CallImportRow,
                CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
            )
            .filter(CallImportEvaluationRow.evaluation_id == eval_id)
            .order_by(CallImportRow.row_index.asc())
            .all()
        )
    report_config = payload.report_config if isinstance(payload.report_config, dict) else {}
    metrics = _display_metrics_for_pdf_report(db, organization_id, evaluation)
    configured_quality_ids = {
        str(item)
        for item in report_config.get("quality_metric_ids", [])
        if item
    }
    configured_insight_ids = {
        str(item.get("metric_id") or item)
        for item in report_config.get("insights", [])
        if item
    }
    if configured_quality_ids or configured_insight_ids:
        allowed_ids = configured_quality_ids | configured_insight_ids
        metrics = [metric for metric in metrics if str(metric.id) in allowed_ids]

    eval_rows = [eval_row for eval_row, _source_row in rows]
    aggregate_models = _compute_metric_aggregates(db, evaluation, eval_rows)
    selected_report_metric_ids = {str(metric.id) for metric in metrics}
    aggregate_dicts = [
        _aggregate_to_dict(aggregate)
        for aggregate in aggregate_models
        if aggregate.metric_id in selected_report_metric_ids
    ]
    insight_metric_ids = {
        str(metric.id)
        for metric in metrics
        if _metric_is_user_insight(metric)
    }
    metric_aggregates = [
        item for item in aggregate_dicts if str(item.get("metric_id")) not in insight_metric_ids
    ]
    insight_aggregates = [
        item for item in aggregate_dicts if str(item.get("metric_id")) in insight_metric_ids
    ]
    period_start, period_end, derived_period_label, period_display = _report_period_from_rows(rows)
    period_label = (payload.period_label or derived_period_label or "").strip() or None
    include_period_delta = (
        payload.include_period_delta or payload.include_weekly_delta
    )
    previous_snapshot = None
    period_delta_by_metric: dict[str, dict[str, str]] = {}
    baseline_evaluation: Optional[CallImportEvaluation] = None
    if include_period_delta and period_start:
        baseline_evaluation = _resolve_baseline_evaluation(
            db,
            organization_id,
            call_import.workspace_id,
            evaluation,
            period_start,
            payload.baseline_evaluation_id,
        )
        if baseline_evaluation:
            period_delta_by_metric = _period_deltas_from_evaluation(
                db,
                baseline_evaluation,
                metric_aggregates,
                evaluation,
                [eval_row for eval_row, _ in rows],
            )
            period_delta_by_metric = _period_deltas_with_explanations(
                db,
                organization_id,
                evaluation,
                baseline_evaluation,
                period_delta_by_metric,
            )
    benchmark_context = _benchmark_context_for_evaluation(db, baseline_evaluation)
    evidence_samples = _sample_evidence_for_metrics(rows, insight_metric_ids)
    cached_tldr_summary = _tldr_summary_payload(evaluation)
    cached_user_insights = _user_insights_payload(evaluation)
    cached_metric_clusters = _metric_clusters_payload(evaluation)
    cached_prompt_improvements = _prompt_improvements_payload(evaluation)
    generated_insights_for_pdf = _selected_generated_user_insights(
        cached_user_insights,
        report_config,
    )
    metric_clusters_for_pdf = _selected_metric_clusters_for_pdf(
        cached_metric_clusters,
        report_config,
    )
    prompt_improvements_for_pdf = _selected_prompt_improvements_for_pdf(
        cached_prompt_improvements,
        report_config,
    )
    branding_images, custom_heading = _report_branding_for_import_workspace(
        db,
        organization_id,
        call_import.workspace_id,
        internal_brand_image_id=payload.internal_brand_image_id,
        external_brand_image_id=payload.external_brand_image_id,
    )
    eval_row_list = [eval_row for eval_row, _ in rows]
    pdf_aggregates = _compute_metric_aggregates(db, evaluation, eval_row_list)
    pdf_parent_ids = [
        m.id
        for m in metrics
        if getattr(m, "selection_mode", None)
        and not getattr(m, "parent_metric_id", None)
    ]
    pdf_child_map = _child_names_by_parent(
        db, evaluation.organization_id, pdf_parent_ids
    )
    failure_policies_for_pdf, _fp_source = effective_policies(
        evaluation,
        metrics,
        pdf_aggregates,
        child_names_by_parent=pdf_child_map,
    )

    from app.services.storage.s3_service import s3_service

    config_fingerprint = compute_pdf_report_config_fingerprint(
        report_type=payload.report_type,
        include_period_delta=bool(payload.include_period_delta),
        include_weekly_delta=bool(payload.include_weekly_delta),
        baseline_evaluation_id=payload.baseline_evaluation_id,
        internal_brand_image_id=payload.internal_brand_image_id,
        external_brand_image_id=payload.external_brand_image_id,
        use_case=payload.use_case,
        report_config=report_config,
        report_heading=custom_heading,
        vendor_name=payload.vendor_name,
        platform_base_url=payload.platform_base_url,
        period_label=period_label,
    )
    content_fingerprint = compute_pdf_report_content_fingerprint(
        evaluation_status=evaluation.status,
        completed_rows=int(evaluation.completed_rows or 0),
        total_rows=int(evaluation.total_rows or 0),
        failed_rows=int(evaluation.failed_rows or 0),
        metric_aggregates=metric_aggregates,
        insight_aggregates=insight_aggregates,
        period_delta_by_metric=period_delta_by_metric,
        benchmark_context=benchmark_context,
        metric_metadata=[
            {
                "id": str(metric.id),
                "name": metric.name,
                "description": metric.description,
            }
            for metric in metrics
        ],
        failure_policies=failure_policies_for_pdf,
        tldr_summary=cached_tldr_summary,
        user_insights_for_pdf=generated_insights_for_pdf,
        metric_clusters_for_pdf=metric_clusters_for_pdf,
        prompt_improvements_for_pdf=prompt_improvements_for_pdf,
    )
    cache_fingerprint = compute_pdf_report_cache_fingerprint(
        config_fingerprint=config_fingerprint,
        content_fingerprint=content_fingerprint,
    )
    if s3_service.is_enabled():
        cached_pdf_report = find_cached_pdf_report(
            db,
            evaluation_id=evaluation.id,
            organization_id=organization_id,
            cache_fingerprint=cache_fingerprint,
        )
        if cached_pdf_report is not None:
            logger.info(
                "Reusing stored PDF report {} for evaluation {} (cache fingerprint match)",
                cached_pdf_report.id,
                eval_id,
            )
            return _pdf_report_response_from_row(cached_pdf_report, cache_hit=True)

    from app.services.usage.call_import_context import (
        call_import_evaluation_usage_context,
    )
    from app.services.usage.context import llm_usage_context

    with llm_usage_context(
        call_import_evaluation_usage_context(
            organization_id=organization_id,
            workspace_id=getattr(call_import, "workspace_id", None)
            or evaluation.workspace_id,
            evaluation_id=evaluation.id,
            call_import_id=evaluation.call_import_id,
        )
    ):
        narrative = _generate_report_narrative(
            db,
            organization_id,
            metric_aggregates=metric_aggregates,
            insight_aggregates=insight_aggregates if is_internal else [],
            period_delta_by_metric=period_delta_by_metric,
            evidence_samples=evidence_samples if is_internal else {},
            report_config=report_config,
        )

    generated_at = datetime.now(timezone.utc)
    try:
        pdf_started = datetime.now(timezone.utc)
        pdf_bytes = await asyncio.to_thread(
            call_import_evaluation_pdf_report_service.render_pdf,
            vendor_name=payload.vendor_name,
            call_import=call_import,
            evaluation=evaluation,
            metrics=metrics,
            rows=rows,
            failure_policies=failure_policies_for_pdf,
            generated_at=generated_at,
            internal=is_internal,
            logo_data_uris=branding_images,
            custom_heading=custom_heading,
            include_weekly_delta=include_period_delta,
            period_delta_by_metric=period_delta_by_metric,
            use_case=payload.use_case,
            period_display=period_display,
            total_metric_count=db.query(Metric)
            .filter(Metric.organization_id == organization_id, Metric.enabled.is_(True))
            .count(),
            report_config=report_config,
            narrative=narrative,
            audit_summary=_audit_summary_text_from_tldr(cached_tldr_summary),
            metric_insights=_metric_insights_from_tldr(cached_tldr_summary),
            benchmark_context=benchmark_context,
            generated_user_insights=generated_insights_for_pdf,
            user_insights_overview=(
                cached_user_insights.overview if cached_user_insights else None
            ),
            metric_clusters=metric_clusters_for_pdf,
            metric_clusters_overview=(
                cached_metric_clusters.overview if cached_metric_clusters else None
            ),
            prompt_improvements=prompt_improvements_for_pdf,
            platform_base_url=payload.platform_base_url,
        )
        logger.info(
            "PDF report render finished in {:.1f}s for evaluation {}",
            (datetime.now(timezone.utc) - pdf_started).total_seconds(),
            eval_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to generate PDF report for call import {} evaluation {}",
            call_import_id,
            eval_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate PDF report: {exc}",
        ) from exc

    snapshot = CallImportEvaluationReportSnapshot(
        evaluation_id=evaluation.id,
        call_import_id=call_import.id,
        organization_id=organization_id,
        workspace_id=call_import.workspace_id,
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        report_config=report_config,
        selected_metric_ids=[str(metric.id) for metric in metrics],
        metric_aggregates=metric_aggregates,
        insight_aggregates=insight_aggregates,
        narrative=narrative,
        total_calls=evaluation.total_rows,
        selected_metric_count=len(metrics),
        total_metric_count=db.query(Metric)
        .filter(Metric.organization_id == organization_id, Metric.enabled.is_(True))
        .count(),
    )
    db.add(snapshot)
    db.flush()

    filename = (
        f"{_report_filename_slug(payload.vendor_name)}-"
        f"{payload.report_type}-quality-metric-audit-{eval_id}.pdf"
    )

    if not s3_service.is_enabled():
        db.commit()
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    report_id = uuid4()
    s3_key = build_pdf_report_s3_key(
        organization_id=organization_id,
        call_import_id=call_import.id,
        evaluation_id=evaluation.id,
        report_id=report_id,
    )
    try:
        s3_service.upload_file_by_key(
            file_content=pdf_bytes,
            key=s3_key,
            content_type="application/pdf",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to upload PDF report for evaluation {} to object storage",
            eval_id,
        )
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store PDF report: {exc}",
        ) from exc

    created_by, created_by_user_id = _pdf_report_actor(principal)
    pdf_report = CallImportEvaluationPdfReport(
        id=report_id,
        evaluation_id=evaluation.id,
        call_import_id=call_import.id,
        organization_id=organization_id,
        workspace_id=call_import.workspace_id,
        snapshot_id=snapshot.id,
        vendor_name=payload.vendor_name,
        report_type=payload.report_type,
        filename=filename,
        s3_key=s3_key,
        report_config=report_config,
        cache_fingerprint=cache_fingerprint,
        created_by=created_by,
        created_by_user_id=created_by_user_id,
    )
    db.add(pdf_report)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        try:
            s3_service.delete_file_by_key(s3_key)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to delete orphan PDF after cache race for evaluation {}",
                eval_id,
            )
        raced_winner = find_cached_pdf_report(
            db,
            evaluation_id=evaluation.id,
            organization_id=organization_id,
            cache_fingerprint=cache_fingerprint,
        )
        if raced_winner is not None:
            logger.info(
                "PDF report cache race resolved for evaluation {} (winner {})",
                eval_id,
                raced_winner.id,
            )
            return _pdf_report_response_from_row(raced_winner, cache_hit=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to store PDF report due to a concurrent duplicate request.",
        ) from None
    db.refresh(pdf_report)
    from app.services.billing.flexprice_service import (
        record_call_import_pdf_report_generated,
    )

    record_call_import_pdf_report_generated(
        organization_id,
        pdf_report.id,
        workspace_id=pdf_report.workspace_id,
        evaluation_id=evaluation.id,
        call_import_id=call_import_id,
        report_type=pdf_report.report_type,
    )
    return _pdf_report_response_from_row(pdf_report)

def pdf_report_download_response(
    db: Session,
    *,
    call_import_id: UUID,
    eval_id: UUID,
    report_id: UUID,
    organization_id: UUID,
) -> StreamingResponse:
    row = (
        db.query(CallImportEvaluationPdfReport)
        .filter(
            CallImportEvaluationPdfReport.id == report_id,
            CallImportEvaluationPdfReport.evaluation_id == eval_id,
            CallImportEvaluationPdfReport.call_import_id == call_import_id,
            CallImportEvaluationPdfReport.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="PDF report not found")
    if not row.s3_key:
        raise HTTPException(
            status_code=404,
            detail="PDF report file is not available in object storage",
        )
    from app.services.storage.s3_service import s3_service

    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Object storage is not enabled or not configured.",
        )
    try:
        file_bytes = s3_service.download_file_by_key(row.s3_key)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to download PDF report {} for evaluation {}",
            report_id,
            eval_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to download PDF report: {exc}",
        ) from exc
    filename = row.filename or "report.pdf"
    safe_name = filename.replace('"', "'")
    return StreamingResponse(
        iter([file_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


pdf_report_response_from_row = _pdf_report_response_from_row
pdf_report_list_item_from_row = _pdf_report_list_item_from_row
