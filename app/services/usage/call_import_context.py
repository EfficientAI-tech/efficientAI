"""Usage context builders for call-import evaluation pipelines."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from app.services.usage.context import LLMUsageContext, LLMUsageProductSection


def _parse_uuid(raw: Any) -> Optional[UUID]:
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def call_import_ids_from_usage_context(ctx: LLMUsageContext) -> dict[str, Optional[UUID]]:
    """Extract call-import linkage ids from a usage context (no DB)."""
    extra = ctx.extra or {}
    ids: dict[str, Optional[UUID]] = {
        "call_import_id": _parse_uuid(extra.get("call_import_id")),
        "evaluation_id": _parse_uuid(extra.get("evaluation_id")),
        "call_import_row_id": _parse_uuid(extra.get("call_import_row_id")),
        "evaluation_row_id": _parse_uuid(extra.get("evaluation_row_id")),
    }
    if ctx.resource_type == "call_import" and ctx.resource_id:
        ids["call_import_id"] = ids["call_import_id"] or ctx.resource_id
    if ctx.resource_type == "call_import_evaluation" and ctx.resource_id:
        ids["evaluation_id"] = ids["evaluation_id"] or ctx.resource_id
    return ids


def resolve_workspace_id_for_usage_context(ctx: LLMUsageContext) -> Optional[UUID]:
    """Resolve workspace from call-import entities when context omitted workspace_id."""
    if ctx.workspace_id is not None:
        return ctx.workspace_id

    ids = call_import_ids_from_usage_context(ctx)
    if not any(ids.values()):
        return None

    from app.database import SessionLocal
    from app.models.database import (
        CallImport,
        CallImportEvaluation,
        CallImportEvaluationRow,
        CallImportRow,
    )

    org_id = ctx.organization_id
    db = SessionLocal()
    try:
        if ids["call_import_id"]:
            ws = (
                db.query(CallImport.workspace_id)
                .filter(
                    CallImport.id == ids["call_import_id"],
                    CallImport.organization_id == org_id,
                )
                .scalar()
            )
            if ws:
                return ws

        if ids["evaluation_id"]:
            ws = (
                db.query(CallImportEvaluation.workspace_id)
                .filter(
                    CallImportEvaluation.id == ids["evaluation_id"],
                    CallImportEvaluation.organization_id == org_id,
                )
                .scalar()
            )
            if ws:
                return ws

        if ids["call_import_row_id"]:
            ws = (
                db.query(CallImportRow.workspace_id)
                .filter(
                    CallImportRow.id == ids["call_import_row_id"],
                    CallImportRow.organization_id == org_id,
                )
                .scalar()
            )
            if ws:
                return ws

        if ids["evaluation_row_id"]:
            ws = (
                db.query(CallImportEvaluation.workspace_id)
                .join(
                    CallImportEvaluationRow,
                    CallImportEvaluationRow.evaluation_id == CallImportEvaluation.id,
                )
                .filter(
                    CallImportEvaluationRow.id == ids["evaluation_row_id"],
                    CallImportEvaluation.organization_id == org_id,
                )
                .scalar()
            )
            if ws:
                return ws

        return None
    finally:
        db.close()


def enrich_usage_context_workspace(ctx: LLMUsageContext) -> LLMUsageContext:
    """Fill workspace_id from call-import linkage when missing at record time."""
    if ctx.workspace_id is not None:
        return ctx
    try:
        resolved = resolve_workspace_id_for_usage_context(ctx)
    except Exception:
        return ctx
    if resolved is None:
        return ctx
    return LLMUsageContext(
        organization_id=ctx.organization_id,
        workspace_id=resolved,
        product_section=ctx.product_section,
        resource_id=ctx.resource_id,
        resource_type=ctx.resource_type,
        extra=ctx.extra,
    )


def call_import_evaluation_usage_context(
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    evaluation_id: UUID,
    call_import_id: UUID,
) -> LLMUsageContext:
    """Usage rollup for an eval run (model-level drilldown; not per recording)."""
    extra: dict[str, str] = {
        "call_import_id": str(call_import_id),
        "evaluation_id": str(evaluation_id),
    }
    return LLMUsageContext(
        organization_id=organization_id,
        workspace_id=workspace_id,
        product_section=LLMUsageProductSection.CALL_IMPORT_EVALUATIONS,
        resource_id=evaluation_id,
        resource_type="call_import_evaluation",
        extra=extra,
    )


def call_import_row_usage_context(
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    call_import_id: UUID,
    evaluation_id: Optional[UUID] = None,
) -> LLMUsageContext:
    """Usage rollup for diarisation / STT (call-import level, not per recording)."""
    if evaluation_id is not None:
        return call_import_evaluation_usage_context(
            organization_id=organization_id,
            workspace_id=workspace_id,
            evaluation_id=evaluation_id,
            call_import_id=call_import_id,
        )
    return LLMUsageContext(
        organization_id=organization_id,
        workspace_id=workspace_id,
        product_section=LLMUsageProductSection.CALL_IMPORTS,
        resource_id=call_import_id,
        resource_type="call_import",
        extra={"call_import_id": str(call_import_id)},
    )


def usage_context_for_evaluation(
    evaluation: Any,
) -> LLMUsageContext:
    """Usage context from a loaded CallImportEvaluation row."""
    return call_import_evaluation_usage_context(
        organization_id=evaluation.organization_id,
        workspace_id=evaluation.workspace_id,
        evaluation_id=evaluation.id,
        call_import_id=evaluation.call_import_id,
    )
