"""Helpers for call import evaluation PDF report storage and config fingerprinting."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.services.storage.s3_service import s3_service

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.database import CallImportEvaluationPdfReport


def build_pdf_report_s3_key(
    *,
    organization_id: UUID,
    call_import_id: UUID,
    evaluation_id: UUID,
    report_id: UUID,
) -> str:
    prefix = s3_service.prefix or ""
    return (
        f"{prefix}organizations/{organization_id}/call_imports/{call_import_id}/"
        f"evaluations/{evaluation_id}/reports/{report_id}.pdf"
    )


def _canonicalize_report_config(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canonicalize_report_config(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        normalized = [_canonicalize_report_config(item) for item in value]
        try:
            return sorted(
                normalized,
                key=lambda item: json.dumps(item, sort_keys=True, default=str),
            )
        except TypeError:
            return normalized
    return value


def _fingerprint_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_fingerprint_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _json_fingerprint_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_fingerprint_value(item) for item in value]
    return value


def compute_pdf_report_config_fingerprint(
    *,
    report_type: str,
    include_period_delta: bool,
    include_weekly_delta: bool,
    baseline_evaluation_id: str | None,
    internal_brand_image_id: str | None,
    external_brand_image_id: str | None,
    use_case: str | None,
    report_config: dict[str, Any],
    report_heading: str | None,
    vendor_name: str | None = None,
    platform_base_url: str | None = None,
    period_label: str | None = None,
) -> str:
    payload = {
        "report_type": report_type,
        "include_period_delta": include_period_delta,
        "include_weekly_delta": include_weekly_delta,
        "baseline_evaluation_id": baseline_evaluation_id,
        "internal_brand_image_id": internal_brand_image_id,
        "external_brand_image_id": external_brand_image_id,
        "use_case": use_case,
        "report_config": _canonicalize_report_config(report_config or {}),
        "report_heading": (report_heading or "").strip(),
        "vendor_name": (vendor_name or "").strip(),
        "platform_base_url": (platform_base_url or "").strip(),
        "period_label": (period_label or "").strip(),
    }
    return _fingerprint_digest(payload)


def compute_pdf_report_content_fingerprint(
    *,
    evaluation_status: str,
    completed_rows: int,
    total_rows: int,
    failed_rows: int,
    metric_aggregates: list[dict[str, Any]],
    insight_aggregates: list[dict[str, Any]],
    period_delta_by_metric: dict[str, Any],
    benchmark_context: Any,
    metric_metadata: list[dict[str, Any]],
    failure_policies: dict[str, Any],
    tldr_summary: Any = None,
    user_insights_for_pdf: Any = None,
    metric_clusters_for_pdf: Any = None,
    prompt_improvements_for_pdf: Any = None,
) -> str:
    payload = {
        "evaluation_status": evaluation_status,
        "completed_rows": completed_rows,
        "total_rows": total_rows,
        "failed_rows": failed_rows,
        "metric_aggregates": _canonicalize_report_config(metric_aggregates or []),
        "insight_aggregates": _canonicalize_report_config(insight_aggregates or []),
        "period_delta_by_metric": _canonicalize_report_config(period_delta_by_metric or {}),
        "benchmark_context": _json_fingerprint_value(benchmark_context),
        "metric_metadata": _canonicalize_report_config(metric_metadata or []),
        "failure_policies": _json_fingerprint_value(failure_policies or {}),
        "tldr_summary": _json_fingerprint_value(tldr_summary),
        "user_insights_for_pdf": _json_fingerprint_value(user_insights_for_pdf),
        "metric_clusters_for_pdf": _json_fingerprint_value(metric_clusters_for_pdf),
        "prompt_improvements_for_pdf": _json_fingerprint_value(prompt_improvements_for_pdf),
    }
    return _fingerprint_digest(payload)


def compute_pdf_report_cache_fingerprint(
    *,
    config_fingerprint: str,
    content_fingerprint: str,
) -> str:
    combined = f"{config_fingerprint}:{content_fingerprint}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def find_cached_pdf_report(
    db: "Session",
    *,
    evaluation_id: UUID,
    organization_id: UUID,
    cache_fingerprint: str,
) -> "CallImportEvaluationPdfReport | None":
    from sqlalchemy import desc

    from app.models.database import CallImportEvaluationPdfReport

    if not cache_fingerprint:
        return None
    return (
        db.query(CallImportEvaluationPdfReport)
        .filter(
            CallImportEvaluationPdfReport.evaluation_id == evaluation_id,
            CallImportEvaluationPdfReport.organization_id == organization_id,
            CallImportEvaluationPdfReport.cache_fingerprint == cache_fingerprint,
            CallImportEvaluationPdfReport.s3_key.isnot(None),
        )
        .order_by(desc(CallImportEvaluationPdfReport.created_at))
        .first()
    )


def config_summary_from_report_config(report_config: dict[str, Any] | None) -> str:
    cfg = report_config if isinstance(report_config, dict) else {}
    quality_ids = cfg.get("quality_metric_ids") or []
    insight_ids = cfg.get("insights") or []
    user_insight_ids = cfg.get("user_insight_ids") or []
    metric_count = len(quality_ids) if isinstance(quality_ids, list) else 0
    insight_count = len(insight_ids) if isinstance(insight_ids, list) else 0
    user_count = len(user_insight_ids) if isinstance(user_insight_ids, list) else 0
    parts: list[str] = []
    if metric_count:
        parts.append(f"{metric_count} quality metric{'s' if metric_count != 1 else ''}")
    if insight_count:
        parts.append(f"{insight_count} insight{'s' if insight_count != 1 else ''}")
    if user_count:
        parts.append(f"{user_count} user insight{'s' if user_count != 1 else ''}")
    return ", ".join(parts) if parts else "default sections"


def presigned_urls_for_pdf_report(
    s3_key: str,
    filename: str,
    *,
    expiration: int = 3600,
) -> tuple[str | None, str | None]:
    if not s3_key or not s3_service.is_enabled():
        return None, None
    safe_name = filename.replace('"', "'")
    try:
        preview_url = s3_service.generate_presigned_url_by_key(
            s3_key,
            expiration=expiration,
            response_content_disposition="inline",
        )
        download_url = s3_service.generate_presigned_url_by_key(
            s3_key,
            expiration=expiration,
            response_content_disposition=f'attachment; filename="{safe_name}"',
        )
        return preview_url, download_url
    except Exception:
        return None, None
