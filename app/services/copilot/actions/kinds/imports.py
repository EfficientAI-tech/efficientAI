"""Call-import actions: map an uploaded file's columns, start/cancel/retry
evaluations, review and push prompt improvements.

All are gated by the ``call_imports`` enterprise feature (the router-level
gate doesn't run when handlers are called directly) and the same workspace
capabilities as the Imports pages.
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth.capabilities import CALLS_IMPORT, EVALS_RUN
from app.models.database import CallImport, CallImportEvaluation, Metric
from app.services.copilot.actions.base import (
    ActionContext,
    ActionKind,
    ActionResult,
    EntityRef,
    register_kind,
)
from app.services.copilot.actions.kinds._common import (
    import_evaluation_or_error,
    import_or_error,
    principal_for,
    require_feature,
)

FEATURE = "call_imports"
_API_KEY_UNUSED = ""  # handlers take an api_key dependency they immediately discard


def _eval_link(evaluation: CallImportEvaluation) -> str:
    return f"/call-imports/{evaluation.call_import_id}/evaluations/{evaluation.id}"


# --- map columns of an uploaded file ----------------------------------------------


class MappingFields(BaseModel):
    call_import_id: UUID
    schema_id: UUID = Field(..., description="Import schema to map to (from get_import_upload).")
    sheet_name: Optional[str] = Field(None, max_length=255)
    parameter_mapping: dict[str, str] = Field(..., description="schema parameter name -> file column header")
    skipped_columns: list[str] = Field(default_factory=list, description="File columns to ignore.")


async def _map_columns(ctx: ActionContext, p: MappingFields) -> ActionResult:
    from app.api.v1.routes.call_imports.core_routes import update_call_import_mapping
    from app.models.schemas import CallImportMappingUpdate

    require_feature(ctx, FEATURE)
    call_import = import_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, p.call_import_id)
    await update_call_import_mapping(
        call_import_id=p.call_import_id,
        payload=CallImportMappingUpdate(
            schema_id=p.schema_id,
            sheet_name=p.sheet_name,
            parameter_mapping=p.parameter_mapping,
            skipped_columns=p.skipped_columns,
        ),
        api_key=_API_KEY_UNUSED,
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        principal=principal_for(ctx),
        db=ctx.db,
    )
    name = call_import.original_filename or "import"
    return ActionResult(
        summary=f"Mapped the columns of '{name}'. It's ready to evaluate.",
        updated=[EntityRef("import", str(call_import.id), name, f"/call-imports/{call_import.id}")],
    )


register_kind(ActionKind(
    kind="map_import_columns",
    title="Map import columns",
    payload_model=MappingFields,
    apply=_map_columns,
    describe=lambda p: f"Map {len(p.parameter_mapping)} column(s), skip {len(p.skipped_columns)}",
    capability=CALLS_IMPORT,
))

# --- start an evaluation ----------------------------------------------------------------


class StartEvaluationFields(BaseModel):
    call_import_id: UUID
    metric_ids: list[UUID] = Field(..., min_length=1, max_length=50)
    name: Optional[str] = Field(None, max_length=255)


def _leaf_metric_count(db: Session, org: UUID, metric_ids: list[UUID]) -> int:
    children = (
        db.query(Metric.parent_metric_id)
        .filter(Metric.organization_id == org, Metric.parent_metric_id.in_(metric_ids), Metric.enabled.is_(True))
        .all()
    )
    parents = {pid for (pid,) in children}
    return len(children) + len([m for m in metric_ids if m not in parents])


def _estimate_evaluation(db: Session, org: UUID, ws: UUID, p: StartEvaluationFields) -> dict[str, Any]:
    call_import = (
        db.query(CallImport)
        .filter(CallImport.id == p.call_import_id, CallImport.organization_id == org, CallImport.workspace_id == ws)
        .first()
    )
    rows = int(call_import.total_rows or 0) if call_import else 0
    metrics = _leaf_metric_count(db, org, p.metric_ids)
    return {
        "calls_to_evaluate": rows,
        "metrics_per_call": metrics,
        "llm_judgements": rows * metrics,
        "note": "Uses your organization's default LLM; billed as an import evaluation.",
    }


async def _start_evaluation(ctx: ActionContext, p: StartEvaluationFields) -> ActionResult:
    from app.models.schemas import CallImportEvaluationCreate
    from app.services.ai.llm_resolver import resolve_org_default_llm
    from app.services.call_imports.evaluation_create import create_call_import_evaluations

    require_feature(ctx, FEATURE)
    import_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, p.call_import_id)
    llm = resolve_org_default_llm(ctx.db, ctx.organization_id)
    if llm is None:
        raise ValueError("No AI provider is configured for this organization.")
    payload = CallImportEvaluationCreate(
        metric_ids=p.metric_ids,
        name=p.name,
        # Production transcripts only: diarising audio needs STT and diarisation
        # models chosen on the import page.
        transcript_sources=["production"],
        auto_transcribe=False,
        llm_provider=llm.provider.value,
        llm_model=llm.model,
        llm_credential_id=llm.credential.id,
    )
    evaluation = create_call_import_evaluations(
        ctx.db,
        organization_id=ctx.organization_id,
        principal=principal_for(ctx),
        call_import_id=p.call_import_id,
        payload=payload,
    )
    eval_id = str(evaluation.id)
    link = f"/call-imports/{p.call_import_id}/evaluations/{eval_id}"
    return ActionResult(
        summary=f"Started evaluation '{evaluation.name or eval_id}' on {evaluation.total_rows} call(s).",
        created=[EntityRef("import evaluation", eval_id, evaluation.name, link)],
        undo_state={"call_import_id": str(p.call_import_id), "evaluation_id": eval_id},
        data={"evaluation_id": eval_id},
    )


async def _cancel_started_evaluation(ctx: ActionContext, state: dict[str, Any]) -> None:
    await _cancel(ctx, CancelEvaluationFields(evaluation_id=UUID(state["evaluation_id"])))


register_kind(ActionKind(
    kind="start_import_evaluation",
    title="Evaluate imported calls",
    payload_model=StartEvaluationFields,
    apply=_start_evaluation,
    undo=_cancel_started_evaluation,
    describe=lambda p: f"Score an import with {len(p.metric_ids)} metric(s)",
    capability=EVALS_RUN,
    costly=True,
    estimate=_estimate_evaluation,
))

# --- cancel / retry ---------------------------------------------------------------------


class CancelEvaluationFields(BaseModel):
    evaluation_id: UUID


async def _cancel(ctx: ActionContext, p: CancelEvaluationFields) -> ActionResult:
    from app.api.v1.routes.call_import_evaluations.evaluation_cancel import cancel_call_import_evaluation

    require_feature(ctx, FEATURE)
    evaluation = import_evaluation_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, p.evaluation_id)
    await cancel_call_import_evaluation(
        call_import_id=evaluation.call_import_id,
        eval_id=evaluation.id,
        api_key=_API_KEY_UNUSED,
        organization_id=ctx.organization_id,
        principal=principal_for(ctx),
        db=ctx.db,
    )
    return ActionResult(
        summary="Stopping the evaluation. Rows already scored are kept.",
        updated=[EntityRef("import evaluation", str(evaluation.id), evaluation.name, _eval_link(evaluation))],
    )


register_kind(ActionKind(
    kind="cancel_import_evaluation",
    title="Stop import evaluation",
    payload_model=CancelEvaluationFields,
    apply=_cancel,
    describe=lambda p: "Stop an import evaluation that's still running",
    capability=EVALS_RUN,
    editable=False,
))


class RetryEvaluationFields(BaseModel):
    evaluation_id: UUID


def _estimate_retry(db: Session, org: UUID, ws: UUID, p: RetryEvaluationFields) -> dict[str, Any]:
    evaluation = (
        db.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == p.evaluation_id, CallImportEvaluation.organization_id == org,
                CallImportEvaluation.workspace_id == ws)
        .first()
    )
    return {"failed_calls_to_retry": int(evaluation.failed_rows or 0) if evaluation else 0}


async def _retry(ctx: ActionContext, p: RetryEvaluationFields) -> ActionResult:
    from app.api.v1.routes.call_import_evaluations.evaluation_retry import retry_call_import_evaluation

    require_feature(ctx, FEATURE)
    evaluation = import_evaluation_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, p.evaluation_id)
    response = await retry_call_import_evaluation(
        call_import_id=evaluation.call_import_id,
        eval_id=evaluation.id,
        payload=None,  # explicit: the Body(...) default would be a truthy FieldInfo
        api_key=_API_KEY_UNUSED,
        organization_id=ctx.organization_id,
        principal=principal_for(ctx),
        db=ctx.db,
    )
    requeued = getattr(response, "requeued", None)
    if requeued is None and isinstance(response, dict):
        requeued = response.get("requeued")
    return ActionResult(
        summary=f"Retrying {requeued or 0} failed call(s).",
        updated=[EntityRef("import evaluation", str(evaluation.id), evaluation.name, _eval_link(evaluation))],
    )


register_kind(ActionKind(
    kind="retry_import_evaluation",
    title="Retry failed calls",
    payload_model=RetryEvaluationFields,
    apply=_retry,
    describe=lambda p: "Re-run the calls that failed in an import evaluation",
    capability=EVALS_RUN,
    costly=True,
    estimate=_estimate_retry,
    editable=False,
))

# --- prompt improvements ------------------------------------------------------------------


class ReviewSuggestion(BaseModel):
    suggestion_id: str = Field(..., max_length=128)
    review_status: Literal["accepted", "rejected", "pending"]
    edited_text: Optional[str] = Field(None, max_length=20_000)


class ReviewFields(BaseModel):
    evaluation_id: UUID
    reviews: list[ReviewSuggestion] = Field(..., min_length=1, max_length=50)


async def _review(ctx: ActionContext, p: ReviewFields) -> ActionResult:
    from app.api.v1.routes.call_import_evaluations.prompts import (
        review_call_import_evaluation_prompt_improvement,
    )
    from app.models.schemas import PromptImprovementReviewUpdate

    require_feature(ctx, FEATURE)
    evaluation = import_evaluation_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, p.evaluation_id)
    for review in p.reviews:
        await review_call_import_evaluation_prompt_improvement(
            call_import_id=evaluation.call_import_id,
            eval_id=evaluation.id,
            body=PromptImprovementReviewUpdate(**review.model_dump()),
            api_key=_API_KEY_UNUSED,
            organization_id=ctx.organization_id,
            principal=principal_for(ctx),
            db=ctx.db,
        )
    accepted = sum(1 for r in p.reviews if r.review_status == "accepted")
    return ActionResult(
        summary=f"Reviewed {len(p.reviews)} suggestion(s): {accepted} accepted.",
        updated=[EntityRef("import evaluation", str(evaluation.id), evaluation.name, _eval_link(evaluation))],
    )


register_kind(ActionKind(
    kind="review_prompt_suggestions",
    title="Review prompt suggestions",
    payload_model=ReviewFields,
    apply=_review,
    describe=lambda p: f"Mark {len(p.reviews)} prompt suggestion(s) accepted/rejected",
    capability=EVALS_RUN,
))


class PushFields(BaseModel):
    evaluation_id: UUID
    push_to_live: bool = Field(True, description="Also update the live agent on its voice platform.")


async def _push(ctx: ActionContext, p: PushFields) -> ActionResult:
    from app.api.v1.routes.call_import_evaluations.prompts import push_call_import_evaluation_prompt
    from app.models.schemas import PromptPushConfirm

    require_feature(ctx, FEATURE)
    evaluation = import_evaluation_or_error(ctx.db, ctx.organization_id, ctx.workspace_id, p.evaluation_id)
    response = await push_call_import_evaluation_prompt(
        call_import_id=evaluation.call_import_id,
        eval_id=evaluation.id,
        body=PromptPushConfirm(confirm="confirm", push_to_live=p.push_to_live),
        api_key=_API_KEY_UNUSED,
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        principal=principal_for(ctx),
        db=ctx.db,
    )
    version = getattr(response, "prompt_version", None)
    detail = f"Now on prompt version {version}." if version else ""
    return ActionResult(
        summary=f"Pushed the accepted suggestions to the agent prompt{' and the live agent' if p.push_to_live else ''}. {detail}",
        updated=[EntityRef("import evaluation", str(evaluation.id), evaluation.name, _eval_link(evaluation))],
    )


register_kind(ActionKind(
    kind="push_prompt_improvements",
    title="Update the agent's prompt",
    payload_model=PushFields,
    apply=_push,
    describe=lambda p: "Apply accepted prompt suggestions to the agent"
    + (" and push it to the live voice platform" if p.push_to_live else ""),
    capability=EVALS_RUN,
    costly=True,  # changes production behaviour: confirm button says so
))
