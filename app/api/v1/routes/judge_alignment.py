"""
Judge Alignment API routes.

Implements the AlignEval-style 4-step workflow:
    1. Source/upload  -> POST /judge-datasets, POST /judge-datasets/upload-csv
    2. Label          -> GET/PATCH judge-samples
    3. Evaluate judge -> POST /judge-datasets/{id}/run
    4. Optimize judge -> POST /judge-datasets/{id}/optimize

Plus settings + model catalog endpoints that drive the UI:
    - GET/PATCH /judge-alignment/settings
    - GET       /judge-alignment/available-models
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.database import get_db
from app.dependencies import (
    get_organization_id,
    get_principal,
    get_workspace_id,
    Principal,
)
from app.services.billing.flexprice_service import record_judge_alignment_run_started
from app.models.database import (
    Agent,
    Evaluator,
    JudgeDataset,
    JudgeRun,
    JudgeSample,
)
from app.services.judge_alignment.dataset_adapters import (
    ALLOWED_SOURCE_TYPES,
    label_counts,
    materialize_samples,
    validate_source_config,
)
from app.services.judge_alignment.metrics import compute_alignment_metrics
from app.services.judge_alignment.model_catalog import list_judge_capable_models
from app.services.judge_alignment.settings import (
    DEFAULTS as SETTINGS_DEFAULTS,
    get_org_settings,
    set_org_settings,
)


router = APIRouter(prefix="/judge-alignment", tags=["judge-alignment"])

# Operator-only knob (CSV upload safety limit). The kill switch
# `judge_alignment.enabled` is read here too so all endpoints respond
# 503 when the feature is disabled deployment-wide.
def _ensure_enabled() -> None:
    if not getattr(app_settings, "JUDGE_ALIGNMENT_ENABLED", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Judge Alignment is disabled by operator configuration.",
        )


def _csv_max_rows() -> int:
    return int(getattr(app_settings, "JUDGE_ALIGNMENT_CSV_MAX_ROWS", 5000))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SettingsResponse(BaseModel):
    min_labels_to_evaluate: int
    min_labels_to_optimize: int
    defaults: Dict[str, int] = Field(default_factory=lambda: dict(SETTINGS_DEFAULTS))


class SettingsUpdate(BaseModel):
    min_labels_to_evaluate: int = Field(..., ge=1)
    min_labels_to_optimize: int = Field(..., ge=1)


class ModelCatalogEntry(BaseModel):
    provider: str
    provider_label: str
    model: str
    label: str


class JudgeDatasetCreate(BaseModel):
    name: str
    description: Optional[str] = None
    source_type: str
    source_config: Dict[str, Any] = Field(default_factory=dict)
    input_field: str = "input"
    output_field: str = "output"


class JudgeDatasetResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    source_type: str
    source_config: Dict[str, Any]
    input_field: str
    output_field: str
    total_samples: int
    labeled_samples: int
    unlabeled_samples: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class JudgeSampleResponse(BaseModel):
    id: UUID
    dataset_id: UUID
    external_id: Optional[str] = None
    input_text: str
    output_text: str
    label: Optional[str] = None
    labeled_by: Optional[str] = None
    labeled_at: Optional[datetime] = None
    extra: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SampleLabelUpdate(BaseModel):
    label: Optional[str] = Field(
        default=None,
        description="One of 'pass' | 'fail' | null (clear).",
    )


class BulkLabelItem(BaseModel):
    sample_id: UUID
    label: Optional[str] = None


class BulkLabelUpdate(BaseModel):
    items: List[BulkLabelItem]


class JudgeRunCreate(BaseModel):
    evaluator_id: UUID
    split: str = Field(default="all", pattern="^(all|dev|test)$")
    sample_ids: Optional[List[UUID]] = None


class JudgeRunResponse(BaseModel):
    id: UUID
    dataset_id: UUID
    evaluator_id: Optional[UUID] = None
    split: str
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    status: str
    metrics: Optional[Dict[str, Any]] = None
    predictions: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None
    gepa_optimization_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class JudgeOptimizeCreate(BaseModel):
    evaluator_id: UUID
    dev_ratio: float = Field(default=0.5, gt=0.0, lt=1.0)
    seed: int = 42
    max_metric_calls: int = Field(default=20, ge=1, le=200)
    minibatch_size: int = Field(default=5, ge=1, le=50)
    agent_id: Optional[UUID] = Field(
        default=None,
        description=(
            "Agent to attribute the optimisation run to. Required only "
            "because the existing PromptOptimizationRun schema has "
            "agent_id NOT NULL. Defaults to the evaluator's agent_id if "
            "set, else any agent in the org."
        ),
    )


class JudgeOptimizeResponse(BaseModel):
    optimization_run_id: UUID
    dev_sample_count: int
    test_sample_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_dataset(dataset: JudgeDataset, db: Session) -> JudgeDatasetResponse:
    total, labeled, unlabeled = label_counts(dataset.id, db)
    return JudgeDatasetResponse(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        source_type=dataset.source_type,
        source_config=dataset.source_config or {},
        input_field=dataset.input_field,
        output_field=dataset.output_field,
        total_samples=total,
        labeled_samples=labeled,
        unlabeled_samples=unlabeled,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


def _get_dataset_or_404(
    dataset_id: UUID,
    organization_id: UUID,
    db: Session,
    workspace_id: Optional[UUID] = None,
) -> JudgeDataset:
    """Fetch a dataset scoped to organization (and optionally workspace).

    All HTTP routes pass ``workspace_id``; internal callers without a request
    context can omit it and fall back to org-level isolation.
    """
    query = db.query(JudgeDataset).filter(
        JudgeDataset.id == dataset_id,
        JudgeDataset.organization_id == organization_id,
    )
    if workspace_id is not None:
        query = query.filter(JudgeDataset.workspace_id == workspace_id)
    dataset = query.first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


# ---------------------------------------------------------------------------
# Settings + model catalog
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=SettingsResponse)
def get_settings(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    _ensure_enabled()
    s = get_org_settings(organization_id, db)
    return SettingsResponse(**s)


@router.patch("/settings", response_model=SettingsResponse)
def update_settings(
    body: SettingsUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    _ensure_enabled()
    s = set_org_settings(
        organization_id,
        db,
        min_labels_to_evaluate=body.min_labels_to_evaluate,
        min_labels_to_optimize=body.min_labels_to_optimize,
    )
    return SettingsResponse(**s)


@router.get("/available-models", response_model=List[ModelCatalogEntry])
def get_available_models(
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    _ensure_enabled()
    return list_judge_capable_models(organization_id, db)


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


@router.get("/datasets", response_model=List[JudgeDatasetResponse])
def list_datasets(
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """List judge datasets in the active workspace."""
    _ensure_enabled()
    rows = (
        db.query(JudgeDataset)
        .filter(
            JudgeDataset.organization_id == organization_id,
            JudgeDataset.workspace_id == workspace_id,
        )
        .order_by(JudgeDataset.created_at.desc())
        .all()
    )
    return [_serialize_dataset(r, db) for r in rows]


@router.post(
    "/datasets",
    response_model=JudgeDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset(
    body: JudgeDatasetCreate,
    principal: Principal = Depends(get_principal),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Create a judge dataset stamped with the active workspace."""
    _ensure_enabled()

    if body.source_type not in ALLOWED_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"source_type must be one of {sorted(ALLOWED_SOURCE_TYPES)}",
        )
    validate_source_config(body.source_type, body.source_config)

    # Transcripts are split into User vs Agent turns by the adapter; the
    # generic 'input'/'output' labels would be misleading in the labeling
    # UI and the judge prompt for that source type.
    if body.source_type == "transcript":
        input_field = "user"
        output_field = "agent"
    else:
        input_field = body.input_field
        output_field = body.output_field

    dataset = JudgeDataset(
        organization_id=principal.organization_id,
        workspace_id=workspace_id,
        name=body.name,
        description=body.description,
        source_type=body.source_type,
        source_config=body.source_config or {},
        input_field=input_field,
        output_field=output_field,
        created_by=getattr(principal, "user_id", None) and str(principal.user_id),
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    if body.source_type != "csv":
        try:
            inserted = materialize_samples(dataset, db, csv_max_rows=_csv_max_rows())
            logger.info(
                f"[JudgeAlignment] Materialised {inserted} samples into dataset {dataset.id}"
            )
        except HTTPException:
            db.delete(dataset)
            db.commit()
            raise
        except Exception as exc:
            logger.error(f"[JudgeAlignment] Failed to materialise samples: {exc}")
            db.delete(dataset)
            db.commit()
            raise HTTPException(status_code=500, detail=str(exc))

    return _serialize_dataset(dataset, db)


@router.post(
    "/datasets/upload-csv",
    response_model=JudgeDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_csv_dataset(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: Optional[str] = Form(None),
    principal: Principal = Depends(get_principal),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Upload an AlignEval-style CSV (columns: id, input, output[, label]) into the active workspace."""
    _ensure_enabled()

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    dataset = JudgeDataset(
        organization_id=principal.organization_id,
        workspace_id=workspace_id,
        name=name,
        description=description,
        source_type="csv",
        source_config={"filename": file.filename, "size_bytes": len(raw)},
        input_field="input",
        output_field="output",
        created_by=getattr(principal, "user_id", None) and str(principal.user_id),
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    try:
        inserted = materialize_samples(
            dataset, db, csv_bytes=raw, csv_max_rows=_csv_max_rows()
        )
        logger.info(
            f"[JudgeAlignment] CSV upload inserted {inserted} samples into dataset {dataset.id}"
        )
    except HTTPException:
        db.delete(dataset)
        db.commit()
        raise
    except Exception as exc:
        db.delete(dataset)
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc))

    return _serialize_dataset(dataset, db)


@router.get("/datasets/{dataset_id}", response_model=JudgeDatasetResponse)
def get_dataset(
    dataset_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _ensure_enabled()
    dataset = _get_dataset_or_404(dataset_id, organization_id, db, workspace_id)
    return _serialize_dataset(dataset, db)


@router.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _ensure_enabled()
    dataset = _get_dataset_or_404(dataset_id, organization_id, db, workspace_id)
    db.delete(dataset)
    db.commit()


# ---------------------------------------------------------------------------
# Samples (labeling)
# ---------------------------------------------------------------------------


@router.get(
    "/datasets/{dataset_id}/samples",
    response_model=List[JudgeSampleResponse],
)
def list_samples(
    dataset_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    only_labeled: Optional[bool] = None,
    skip: int = 0,
    limit: int = 500,
):
    _ensure_enabled()
    _get_dataset_or_404(dataset_id, organization_id, db, workspace_id)

    q = db.query(JudgeSample).filter(JudgeSample.dataset_id == dataset_id)
    if only_labeled is True:
        q = q.filter(JudgeSample.label.isnot(None))
    elif only_labeled is False:
        q = q.filter(JudgeSample.label.is_(None))

    rows = (
        q.order_by(JudgeSample.created_at.asc())
        .offset(max(0, skip))
        .limit(min(max(1, limit), 1000))
        .all()
    )
    return rows


@router.patch("/samples/{sample_id}", response_model=JudgeSampleResponse)
def update_sample_label(
    sample_id: UUID,
    body: SampleLabelUpdate,
    principal: Principal = Depends(get_principal),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Label a judge sample whose parent dataset lives in the active workspace."""
    _ensure_enabled()
    sample = (
        db.query(JudgeSample)
        .join(JudgeDataset, JudgeSample.dataset_id == JudgeDataset.id)
        .filter(
            JudgeSample.id == sample_id,
            JudgeDataset.organization_id == principal.organization_id,
            JudgeDataset.workspace_id == workspace_id,
        )
        .first()
    )
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    label = body.label
    if label is not None:
        if label not in {"pass", "fail"}:
            raise HTTPException(
                status_code=400,
                detail="label must be 'pass', 'fail', or null",
            )
        sample.label = label
        sample.labeled_by = (
            str(principal.user_id) if getattr(principal, "user_id", None) else "api"
        )
        sample.labeled_at = datetime.now(timezone.utc)
    else:
        sample.label = None
        sample.labeled_by = None
        sample.labeled_at = None

    db.commit()
    db.refresh(sample)
    return sample


@router.post("/datasets/{dataset_id}/samples/bulk-label", response_model=Dict[str, int])
def bulk_label_samples(
    dataset_id: UUID,
    body: BulkLabelUpdate,
    principal: Principal = Depends(get_principal),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Apply labels to multiple samples in one call (keyboard-driven flow)."""
    _ensure_enabled()
    _get_dataset_or_404(dataset_id, principal.organization_id, db, workspace_id)

    sample_ids = [item.sample_id for item in body.items]
    rows = (
        db.query(JudgeSample)
        .filter(
            JudgeSample.dataset_id == dataset_id,
            JudgeSample.id.in_(sample_ids),
        )
        .all()
    )
    by_id = {r.id: r for r in rows}

    actor = (
        str(principal.user_id) if getattr(principal, "user_id", None) else "api"
    )
    now = datetime.now(timezone.utc)
    updated = 0
    for item in body.items:
        sample = by_id.get(item.sample_id)
        if not sample:
            continue
        if item.label is None:
            sample.label = None
            sample.labeled_by = None
            sample.labeled_at = None
        elif item.label in {"pass", "fail"}:
            sample.label = item.label
            sample.labeled_by = actor
            sample.labeled_at = now
        else:
            continue
        updated += 1

    db.commit()
    return {"updated": updated, "requested": len(body.items)}


# ---------------------------------------------------------------------------
# Judge runs
# ---------------------------------------------------------------------------


@router.get(
    "/datasets/{dataset_id}/runs",
    response_model=List[JudgeRunResponse],
)
def list_runs(
    dataset_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _ensure_enabled()
    _get_dataset_or_404(dataset_id, organization_id, db, workspace_id)
    rows = (
        db.query(JudgeRun)
        .filter(JudgeRun.dataset_id == dataset_id)
        .order_by(JudgeRun.created_at.desc())
        .all()
    )
    return rows


@router.post(
    "/datasets/{dataset_id}/run",
    response_model=JudgeRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def trigger_judge_run(
    dataset_id: UUID,
    body: JudgeRunCreate,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(get_principal),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Spawn a Celery task to score a (possibly subset of) dataset with a judge."""
    _ensure_enabled()
    organization_id = principal.organization_id
    dataset = _get_dataset_or_404(dataset_id, organization_id, db, workspace_id)

    evaluator = (
        db.query(Evaluator)
        .filter(
            Evaluator.id == body.evaluator_id,
            Evaluator.organization_id == organization_id,
            Evaluator.workspace_id == workspace_id,
        )
        .first()
    )
    if not evaluator:
        raise HTTPException(status_code=404, detail="Evaluator not found")
    if not evaluator.custom_prompt:
        raise HTTPException(
            status_code=400,
            detail="Selected evaluator has no custom_prompt to act as judge.",
        )
    if not evaluator.llm_provider or not evaluator.llm_model:
        raise HTTPException(
            status_code=400,
            detail=(
                "Selected evaluator has no llm_provider/llm_model. "
                "Set them via the Evaluators page first."
            ),
        )

    org_settings = get_org_settings(organization_id, db)
    _, labeled, _ = label_counts(dataset.id, db)
    if labeled < org_settings["min_labels_to_evaluate"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Need at least {org_settings['min_labels_to_evaluate']} labeled "
                f"samples before running the judge (have {labeled})."
            ),
        )

    from app.services.judge_alignment.judge_runner import select_samples_for_split

    sample_id_strs = (
        [str(s) for s in (body.sample_ids or [])] if body.split != "all" else None
    )
    selected_samples = select_samples_for_split(
        dataset_id=dataset.id,
        split=body.split,
        db=db,
        sample_ids=sample_id_strs,
    )
    sample_count = len(selected_samples)

    judge_run = JudgeRun(
        dataset_id=dataset.id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        evaluator_id=evaluator.id,
        split=body.split,
        llm_provider=evaluator.llm_provider,
        llm_model=evaluator.llm_model,
        status="queued",
        created_by=(
            str(principal.user_id) if getattr(principal, "user_id", None) else None
        ),
    )
    db.add(judge_run)
    db.commit()
    db.refresh(judge_run)

    try:
        from app.workers.tasks.run_judge_alignment import run_judge_alignment_task

        async_result = run_judge_alignment_task.delay(
            str(judge_run.id), sample_id_strs
        )
        judge_run.celery_task_id = async_result.id
        db.commit()
        db.refresh(judge_run)
        background_tasks.add_task(
            record_judge_alignment_run_started,
            organization_id,
            judge_run.id,
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            sample_count=sample_count,
        )
    except Exception as exc:
        logger.error(f"[JudgeAlignment] Failed to enqueue judge task: {exc}")
        judge_run.status = "failed"
        judge_run.error_message = f"Could not enqueue task: {exc}"
        db.commit()

    return judge_run


@router.get("/runs/{run_id}", response_model=JudgeRunResponse)
def get_run(
    run_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _ensure_enabled()
    run = (
        db.query(JudgeRun)
        .filter(
            JudgeRun.id == run_id,
            JudgeRun.organization_id == organization_id,
            JudgeRun.workspace_id == workspace_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Judge run not found")
    return run


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(
    run_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Delete a single judge run. In-flight runs cannot be deleted."""
    _ensure_enabled()
    run = (
        db.query(JudgeRun)
        .filter(
            JudgeRun.id == run_id,
            JudgeRun.organization_id == organization_id,
            JudgeRun.workspace_id == workspace_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Judge run not found")

    if run.status in {"running", "queued", "pending"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot delete a run that is still in flight. Wait for it to "
                "finish or fail before deleting."
            ),
        )

    db.delete(run)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Optimisation (GEPA bridge)
# ---------------------------------------------------------------------------


@router.post(
    "/datasets/{dataset_id}/optimize",
    response_model=JudgeOptimizeResponse,
    status_code=status.HTTP_201_CREATED,
)
def optimize_judge(
    dataset_id: UUID,
    body: JudgeOptimizeCreate,
    principal: Principal = Depends(get_principal),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Kick off a GEPA optimisation of the judge prompt against this dataset."""
    _ensure_enabled()
    organization_id = principal.organization_id
    dataset = _get_dataset_or_404(dataset_id, organization_id, db, workspace_id)

    evaluator = (
        db.query(Evaluator)
        .filter(
            Evaluator.id == body.evaluator_id,
            Evaluator.organization_id == organization_id,
            Evaluator.workspace_id == workspace_id,
        )
        .first()
    )
    if not evaluator:
        raise HTTPException(status_code=404, detail="Evaluator not found")

    org_settings = get_org_settings(organization_id, db)
    _, labeled, _ = label_counts(dataset.id, db)
    if labeled < org_settings["min_labels_to_optimize"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Need at least {org_settings['min_labels_to_optimize']} labeled "
                f"samples to optimise (have {labeled})."
            ),
        )

    # Resolve agent_id needed by the existing PromptOptimizationRun schema.
    agent_uuid = body.agent_id or evaluator.agent_id
    if not agent_uuid:
        any_agent = (
            db.query(Agent)
            .filter(
                Agent.organization_id == organization_id,
                Agent.workspace_id == workspace_id,
            )
            .order_by(Agent.created_at.asc())
            .first()
        )
        if not any_agent:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No agent available to attribute the optimisation run to. "
                    "Create at least one agent (Agents page) first, or pass "
                    "agent_id explicitly."
                ),
            )
        agent_uuid = any_agent.id

    from app.services.judge_alignment.gepa_bridge import start_gepa_for_dataset

    try:
        run, dev_ids, test_ids = start_gepa_for_dataset(
            dataset=dataset,
            evaluator=evaluator,
            db=db,
            config={
                "agent_id": str(agent_uuid),
                "dev_ratio": body.dev_ratio,
                "seed": body.seed,
                "max_metric_calls": body.max_metric_calls,
                "minibatch_size": body.minibatch_size,
            },
            created_by=(
                str(principal.user_id)
                if getattr(principal, "user_id", None)
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        from app.workers.tasks.run_prompt_optimization import (
            run_prompt_optimization_task,
        )

        run_prompt_optimization_task.delay(str(run.id))
    except Exception as exc:
        logger.error(f"[JudgeAlignment] Failed to enqueue GEPA task: {exc}")
        run.status = "failed"
        run.error_message = f"Could not enqueue task: {exc}"
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc))

    return JudgeOptimizeResponse(
        optimization_run_id=run.id,
        dev_sample_count=len(dev_ids),
        test_sample_count=len(test_ids),
    )


# ---------------------------------------------------------------------------
# Convenience: recompute metrics from existing predictions (no LLM calls)
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/recompute-metrics", response_model=JudgeRunResponse)
def recompute_metrics(
    run_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Recompute metrics for an existing run in the active workspace."""
    _ensure_enabled()
    run = (
        db.query(JudgeRun)
        .filter(
            JudgeRun.id == run_id,
            JudgeRun.organization_id == organization_id,
            JudgeRun.workspace_id == workspace_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Judge run not found")
    predictions = run.predictions or {}
    if not predictions:
        raise HTTPException(status_code=400, detail="No predictions on this run.")

    sample_ids = [UUID(sid) for sid in predictions.keys()]
    samples = (
        db.query(JudgeSample).filter(JudgeSample.id.in_(sample_ids)).all()
    )
    label_by_id = {str(s.id): s.label for s in samples}

    labels: List[Optional[str]] = []
    preds: List[Optional[str]] = []
    for sid, p in predictions.items():
        labels.append(label_by_id.get(sid))
        preds.append(p.get("prediction") if isinstance(p, dict) else None)

    run.metrics = compute_alignment_metrics(labels, preds)
    db.commit()
    db.refresh(run)
    return run


from app.core.auth.capabilities import EVALS_RUN, EVALS_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=EVALS_VIEW,
    manage_capability=EVALS_RUN,
    run_capability=EVALS_RUN,
)
