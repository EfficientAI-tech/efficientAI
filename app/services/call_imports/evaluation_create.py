"""Create call-import evaluation runs (validation, persistence, enqueue)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import Principal
from app.models.database import AIProvider, CallImportEvaluation, Metric
from app.models.enums import ModelProvider
from app.models.schemas import CallImportEvaluationCreate, CallImportEvaluationResponse
from app.services.call_imports.audit import stamp_call_import_actor, stamp_evaluation_actor
from app.api.v1.routes.call_import_evaluations._shared import (
    _expand_metric_selection,
    _normalize_name,
    _require_import,
    _serialize_eval,
)


def create_call_import_evaluations(
    db: Session,
    *,
    organization_id: UUID,
    principal: Principal,
    call_import_id: UUID,
    payload: CallImportEvaluationCreate,
) -> CallImportEvaluationResponse:
    call_import = _require_import(db, call_import_id, organization_id)

    metric_ids = payload.metric_ids
    if not metric_ids:
        raise HTTPException(
            status_code=400,
            detail="Select at least one metric to run the evaluation against.",
        )

    org_metrics = (
        db.query(Metric)
        .filter(
            Metric.organization_id == organization_id,
            Metric.id.in_(metric_ids),
        )
        .all()
    )
    by_id = {metric.id: metric for metric in org_metrics}
    unknown_ids = [mid for mid in metric_ids if mid not in by_id]
    if unknown_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                "These metric ids do not exist in your organization: "
                f"{', '.join(str(mid) for mid in unknown_ids)}. "
                "Refresh the metrics list and try again."
            ),
        )
    draft_metrics = [
        metric
        for metric in org_metrics
        if (getattr(metric, "lifecycle", None) or "active") == "draft"
    ]
    if draft_metrics:
        names = ", ".join(metric.name for metric in draft_metrics)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Draft metrics cannot be used in call import evaluations: {names}. "
                "Promote them in Metrics Studio first."
            ),
        )
    # Parents themselves are containers, not scored rows, so a disabled
    # parent shouldn't block the run as long as it has enabled children.
    # We only reject disabled rows that the worker will actually try to
    # evaluate (children + standalone leaves).
    disabled_leaves = [
        metric
        for metric in org_metrics
        if not metric.enabled
        and not (metric.selection_mode and not metric.parent_metric_id)
    ]
    if disabled_leaves:
        names = ", ".join(metric.name for metric in disabled_leaves)
        raise HTTPException(
            status_code=400,
            detail=(
                f"These metrics are disabled and cannot be evaluated: {names}. "
                "Enable them on the Metrics page (or pick different ones) and "
                "try again."
            ),
        )

    # Expand hierarchical selection: parents auto-include their enabled
    # children, mixed parent+child selections respect the user's subset.
    effective_metrics, parent_to_children = _expand_metric_selection(
        db, organization_id, metric_ids
    )
    if not effective_metrics:
        raise HTTPException(
            status_code=400,
            detail=(
                "None of the selected metrics yielded an enabled leaf to "
                "evaluate. Check that parent categories have enabled "
                "children, then try again."
            ),
        )

    # The effective list (children + standalone leaves) is what gets
    # persisted to ``selected_metric_ids`` and scored by the worker.
    # The original parents are preserved in ``selected_metric_groups``
    # so the UI can rebuild the tree later.
    leaf_metric_ids: List[UUID] = [m.id for m in effective_metrics]
    selected_metric_groups: Dict[str, List[str]] = {
        str(pid): [str(c.id) for c in children]
        for pid, children in parent_to_children.items()
    }
    metric_rows = effective_metrics
    valid_metric_id_strs = {str(m.id) for m in metric_rows}

    # ----- Validate run-level + per-metric LLM config -----
    llm_provider_norm: Optional[str] = None
    llm_model_norm: Optional[str] = None
    if payload.llm_provider or payload.llm_model:
        if not (payload.llm_provider and payload.llm_model):
            raise HTTPException(
                status_code=400,
                detail="Both llm_provider and llm_model are required when overriding the run LLM.",
            )
        try:
            llm_provider_norm = ModelProvider(
                payload.llm_provider.lower()
            ).value
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown LLM provider '{payload.llm_provider}'. "
                    "Valid keys are documented in ModelProvider."
                ),
            )
        llm_model_norm = payload.llm_model.strip() or None
        if not llm_model_norm:
            raise HTTPException(
                status_code=400, detail="llm_model cannot be empty."
            )

    if payload.llm_credential_id is not None:
        cred = (
            db.query(AIProvider)
            .filter(
                AIProvider.id == payload.llm_credential_id,
                AIProvider.organization_id == organization_id,
            )
            .first()
        )
        if not cred:
            raise HTTPException(
                status_code=400,
                detail=(
                    "The provided llm_credential_id does not exist in this "
                    "organization."
                ),
            )

    # Per-metric overrides: keys can be either a leaf metric id (applies
    # to that metric only) or a parent metric id (applies to every
    # child of that parent). Parent keys are expanded to their
    # children so the worker only sees concrete leaf ids.
    metric_overrides_payload: Optional[Dict[str, Dict[str, Any]]] = None
    if payload.metric_llm_overrides:
        metric_overrides_payload = {}
        for metric_id, override in payload.metric_llm_overrides.items():
            target_leaf_ids: List[str] = []
            if metric_id in valid_metric_id_strs:
                target_leaf_ids = [metric_id]
            else:
                # Maybe it's a parent id — expand to the children that
                # are part of THIS run.
                try:
                    parent_uuid = UUID(metric_id)
                except (TypeError, ValueError):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "metric_llm_overrides references metric "
                            f"{metric_id} which is not a valid UUID."
                        ),
                    )
                children_for_parent = parent_to_children.get(parent_uuid)
                if not children_for_parent:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "metric_llm_overrides references metric "
                            f"{metric_id} which is not in metric_ids."
                        ),
                    )
                target_leaf_ids = [str(c.id) for c in children_for_parent]

            override_dict: Dict[str, Any] = {}
            if override.provider is not None:
                if not override.model:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Override for metric {metric_id} has a provider "
                            "but no model."
                        ),
                    )
                try:
                    override_dict["provider"] = ModelProvider(
                        override.provider.lower()
                    ).value
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Override for metric {metric_id} uses unknown "
                            f"provider '{override.provider}'."
                        ),
                    )
                override_dict["model"] = override.model.strip()
            elif override.model:
                # Model without provider doesn't make sense — treat as 400
                # so the UI can fix it instead of silently falling back.
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Override for metric {metric_id} has a model but "
                        "no provider."
                    ),
                )
            if override.credential_id is not None:
                override_dict["credential_id"] = str(override.credential_id)
            if override.llm_config is not None:
                override_dict["llm_config"] = override.llm_config
            if override_dict:
                for leaf_id in target_leaf_ids:
                    metric_overrides_payload[leaf_id] = override_dict

    # ----- Validate auto-transcribe settings -----
    # Diarised runs auto-diarise rows missing a diarised transcript and
    # require STT + diariser LLM config. Production runs score the CSV
    # transcript directly and skip diarisation entirely.
    use_diarised = payload.transcript_sources[0] == "diarised"
    auto_transcribe = use_diarised

    transcribe_mode_norm: Optional[str] = None
    stt_provider_norm: Optional[str] = None
    stt_model_norm: Optional[str] = None
    diarisation_llm_provider_norm: Optional[str] = None
    diarisation_llm_model_norm: Optional[str] = None
    diarisation_prompt_norm: Optional[str] = None

    if use_diarised:
        transcribe_mode_norm = (payload.transcribe_mode or "stt_llm").strip().lower()
        if transcribe_mode_norm not in {"stt_llm", "llm_only"}:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown transcribe_mode '{payload.transcribe_mode}'. "
                    "Expected 'stt_llm' or 'llm_only'."
                ),
            )

        if transcribe_mode_norm == "stt_llm":
            if not payload.stt_provider:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "stt_provider is required when "
                        "transcribe_mode='stt_llm': every evaluation run "
                        "auto-diarises rows that are missing a diarised "
                        "transcript."
                    ),
                )
            if not payload.stt_model:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "stt_model is required when transcribe_mode='stt_llm'."
                    ),
                )
            try:
                stt_provider_norm = ModelProvider(
                    payload.stt_provider.lower()
                ).value
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown STT provider '{payload.stt_provider}'.",
                )
            stt_model_norm = payload.stt_model.strip() or None
            if not stt_model_norm:
                raise HTTPException(
                    status_code=400, detail="stt_model cannot be empty."
                )
        else:
            # llm_only — explicitly reject lingering STT inputs so the
            # contract is unambiguous (the worker would ignore them but
            # silent acceptance hides accidental misconfiguration).
            if (payload.stt_provider or "").strip() or (
                payload.stt_model or ""
            ).strip():
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "stt_provider / stt_model must be omitted when "
                        "transcribe_mode='llm_only'; the LLM consumes the "
                        "audio directly."
                    ),
                )

        # --- Validate LLM diariser settings -----
        if not payload.diarization_llm_provider:
            raise HTTPException(
                status_code=400,
                detail=(
                    "diarization_llm_provider is required: every evaluation "
                    "run diarises STT output with an LLM."
                ),
            )
        if not payload.diarization_llm_model:
            raise HTTPException(
                status_code=400,
                detail=(
                    "diarization_llm_model is required: every evaluation "
                    "run diarises STT output with an LLM."
                ),
            )
        try:
            diarisation_llm_provider_norm = ModelProvider(
                payload.diarization_llm_provider.lower()
            ).value
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown diarisation LLM provider "
                    f"'{payload.diarization_llm_provider}'."
                ),
            )
        diarisation_llm_model_norm = (
            payload.diarization_llm_model.strip() or None
        )
        if not diarisation_llm_model_norm:
            raise HTTPException(
                status_code=400,
                detail="diarization_llm_model cannot be empty.",
            )
        diarisation_prompt_norm = (
            payload.diarization_prompt.strip()
            if isinstance(payload.diarization_prompt, str)
            else None
        ) or None

    from app.models.enums import CallImportParameterType, CallImportStatus
    from app.services.call_imports.bulk_ops import (
        count_all_source_rows,
        count_source_rows_with_production_transcript,
    )

    if use_diarised:
        from app.api.v1.routes.call_imports import (
            _is_manual_audio_call_import,
            _is_platform_call_import,
            platform_import_hydration_complete,
        )

        if not _is_manual_audio_call_import(call_import) and not _is_platform_call_import(
            call_import
        ):
            if call_import.schema_id:
                from app.api.v1.routes.call_imports import (
                    _resolve_schema,
                    _validate_diarised_eval_recording_ready,
                )

                diarised_schema = _resolve_schema(
                    db, organization_id, call_import.workspace_id, call_import.schema_id
                )
                _validate_diarised_eval_recording_ready(
                    list(diarised_schema.parameters),
                    dict(call_import.parameter_mapping or {}),
                )
            else:
                legacy_recording_column = (
                    (call_import.column_mapping or {}).get("recording_url") or ""
                ).strip()
                if not legacy_recording_column:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Diarize then evaluate requires a recording URL column "
                            "to be mapped."
                        ),
                    )

    starting_from_mapped = False
    from app.api.v1.routes.call_imports import (
        _is_platform_call_import,
        platform_import_hydration_complete,
    )

    if _is_platform_call_import(call_import) and not platform_import_hydration_complete(
        call_import
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Platform import is still discovering or fetching recordings. "
                "Wait until the batch is ready before running evaluation."
            ),
        )

    if call_import.status == CallImportStatus.MAPPED:
        if not call_import.source_s3_key or not call_import.source_format:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This batch has no staged source file. Upload and map "
                    "a CSV/Excel file before running evaluation."
                ),
            )
        if not call_import.schema_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot run evaluation without a mapped schema.",
            )
        from app.api.v1.routes.call_imports import (
            _ensure_blob_storage_enabled,
            _resolve_schema,
            _resolve_telephony_integration,
            _validate_direct_url_import_ready,
            _validate_telephony_credentials_live,
        )

        workspace_id = call_import.workspace_id
        schema = _resolve_schema(
            db, organization_id, workspace_id, call_import.schema_id
        )
        parameters = list(schema.parameters)
        if not use_diarised:
            transcript_mapped = any(
                param.type == CallImportParameterType.TRANSCRIPT
                and (call_import.parameter_mapping or {}).get(param.name)
                for param in parameters
            )
            if not transcript_mapped:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "No transcript column is mapped in this batch. "
                        "Map a schema transcript parameter to a CSV column, "
                        "or choose 'Diarize then evaluate'."
                    ),
                )
        if payload.telephony_integration_id is not None:
            integration = _resolve_telephony_integration(
                db,
                organization_id,
                payload.telephony_integration_id,
                payload.provider or "",
            )
            _validate_telephony_credentials_live(db, organization_id, integration)
        else:
            _validate_direct_url_import_ready(
                parameters, dict(call_import.parameter_mapping or {})
            )
            integration = None

        _ensure_blob_storage_enabled()

        if integration is not None:
            call_import.provider = integration.provider
            call_import.telephony_integration_id = integration.id
        else:
            call_import.provider = None
            call_import.telephony_integration_id = None

        call_import.total_rows = 0
        call_import.completed_rows = 0
        call_import.failed_rows = 0
        call_import.error_message = None
        call_import.status = CallImportStatus.PROCESSING
        stamp_call_import_actor(call_import, principal)
        db.commit()
        db.refresh(call_import)
        starting_from_mapped = True

    all_source_row_count = count_all_source_rows(db, call_import.id)

    if use_diarised:
        # Diarized runs materialize every import row; recording fetch may
        # still be pending when switching from a production eval-primary run.
        total_row_count = all_source_row_count
    else:
        # Production runs score CSV text — rows need not wait for
        # recording fetch to finish before they are evaluable.
        total_row_count = count_source_rows_with_production_transcript(
            db, call_import.id
        )

    if (
        use_diarised
        and not starting_from_mapped
        and all_source_row_count > 0
        and call_import.status != CallImportStatus.DELETING
    ):
        call_import.status = CallImportStatus.PROCESSING
        stamp_call_import_actor(call_import, principal)
        db.commit()
        db.refresh(call_import)

    requested_sources: List[str] = list(payload.transcript_sources)

    if (
        not use_diarised
        and not starting_from_mapped
        and count_all_source_rows(db, call_import.id) > 0
        and total_row_count == 0
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No rows have a production transcript. "
                "Choose 'Diarize then evaluate' or import rows with "
                "a transcript column."
            ),
        )

    base_name = _normalize_name(payload.name)

    def _name_for_source(source: str) -> Optional[str]:
        # Single-source runs preserve the user's chosen name verbatim.
        del source
        return base_name

    created_evaluations: List[CallImportEvaluation] = []

    for source in requested_sources:
        evaluation = CallImportEvaluation(
            call_import_id=call_import.id,
            organization_id=organization_id,
            # Mirror the parent CallImport's workspace so listings can
            # filter on workspace_id directly without joining.
            workspace_id=call_import.workspace_id,
            name=_name_for_source(source),
            selected_metric_ids=[
                str(metric_id) for metric_id in leaf_metric_ids
            ],
            selected_metric_groups=selected_metric_groups or None,
            status="pending",
            total_rows=total_row_count,
            completed_rows=0,
            failed_rows=0,
            llm_provider=llm_provider_norm,
            llm_model=llm_model_norm,
            llm_credential_id=payload.llm_credential_id,
            llm_config=payload.llm_config,
            metric_llm_overrides=metric_overrides_payload,
            stt_provider=stt_provider_norm,
            stt_model=stt_model_norm,
            stt_credential_id=(
                payload.stt_credential_id if auto_transcribe else None
            ),
            diarisation_llm_provider=diarisation_llm_provider_norm,
            diarisation_llm_model=diarisation_llm_model_norm,
            diarisation_llm_credential_id=(
                payload.diarization_llm_credential_id if auto_transcribe else None
            ),
            diarisation_prompt=diarisation_prompt_norm,
            transcribe_mode=transcribe_mode_norm,
            transcript_source=source,
            discover_new_metrics=bool(
                getattr(payload, "discover_new_metrics", False)
            ),
        )
        stamp_evaluation_actor(evaluation, principal, creating=True)
        db.add(evaluation)
        db.flush()
        created_evaluations.append(evaluation)

    db.commit()
    for evaluation in created_evaluations:
        db.refresh(evaluation)

    primary_evaluation = created_evaluations[0]
    sibling_ids = [e.id for e in created_evaluations[1:]]

    if not all_source_row_count and not starting_from_mapped:
        for evaluation in created_evaluations:
            evaluation.status = "completed"
        db.commit()
        for evaluation in created_evaluations:
            db.refresh(evaluation)
        return _serialize_eval(
            db, primary_evaluation, sibling_evaluation_ids=sibling_ids
        )

    if starting_from_mapped:
        from app.workers.tasks.call_import_bulk_ops import (
            materialize_mapped_call_import_evaluation_task,
        )

        for evaluation in created_evaluations:
            materialize_mapped_call_import_evaluation_task.delay(
                str(call_import.id),
                str(organization_id),
                str(call_import.workspace_id),
                str(evaluation.id),
                transcribe_overwrite=payload.transcribe_overwrite,
            )
    else:
        from app.workers.tasks.call_import_bulk_ops import (
            materialize_call_import_evaluation_task,
        )

        for evaluation in created_evaluations:
            materialize_call_import_evaluation_task.delay(
                str(evaluation.id),
                transcribe_overwrite=payload.transcribe_overwrite,
            )

    from app.services.billing.flexprice_service import (
        record_call_import_evaluation_started,
    )

    for evaluation in created_evaluations:
        record_call_import_evaluation_started(
            organization_id,
            evaluation.id,
            workspace_id=evaluation.workspace_id,
            call_import_id=call_import.id,
            total_rows=int(evaluation.total_rows or 0),
            metric_count=len(leaf_metric_ids),
        )

    for evaluation in created_evaluations:
        db.refresh(evaluation)

    return _serialize_eval(
        db, primary_evaluation, sibling_evaluation_ids=sibling_ids
    )
