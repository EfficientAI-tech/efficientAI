"""Validation and row materialization helpers for call-import batches."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.database import CallImport, CallImportRow, CallImportSchemaParameter, TelephonyIntegration
from app.models.enums import CallImportParameterType, CallImportRowStatus
from app.services.call_imports.source_parse import (
    _parameter_is_required,
    _parse_recording_date_cell,
)

STUCK_PENDING_ERROR_MARKERS = (
    "rejected credentials",
    "telephony credentials rejected",
    "auth failed",
    "recording fetch failed after",
)


def normalize_content_modality(content_modality: Optional[str]) -> Optional[str]:
    if content_modality is None or not content_modality.strip():
        return None
    mod = content_modality.strip().lower()
    if mod not in ("chat", "voice"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="content_modality must be 'chat' or 'voice' when provided.",
        )
    return mod


def validate_direct_url_import_ready(
    parameters: List[CallImportSchemaParameter],
    parameter_mapping: Dict[str, Any],
) -> None:
    rec_url_param = next(
        (
            p
            for p in parameters
            if p.type == CallImportParameterType.RECORDING_URL.value
        ),
        None,
    )
    if rec_url_param is None:
        return
    if not _parameter_is_required(rec_url_param):
        return
    mapped_header = (parameter_mapping or {}).get(rec_url_param.name)
    if not (mapped_header or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Direct URL import requires the 'recording_url' parameter to "
                "be mapped to a source column."
            ),
        )


def validate_credentialed_import_ready(
    provider: str,
    parameters: List[CallImportSchemaParameter],
    parameter_mapping: Dict[str, Any],
) -> None:
    provider_key = (provider or "").lower()
    provider_label = provider_key.capitalize()
    rec_url_param = next(
        (
            p
            for p in parameters
            if p.type == CallImportParameterType.RECORDING_URL.value
        ),
        None,
    )
    if rec_url_param is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{provider_label} import requires a schema parameter of type "
                "'recording_url'."
            ),
        )
    mapped_header = (parameter_mapping or {}).get(rec_url_param.name)
    if not (mapped_header or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{provider_label} import requires the 'recording_url' parameter to "
                "be mapped to a source column."
            ),
        )


def validate_exotel_import_ready(
    parameters: List[CallImportSchemaParameter],
    parameter_mapping: Dict[str, Any],
) -> None:
    validate_credentialed_import_ready("exotel", parameters, parameter_mapping)


def is_manual_audio_call_import(call_import: CallImport) -> bool:
    return (call_import.source_format or "").lower() == "audio"


def is_platform_call_import(call_import: CallImport) -> bool:
    return (call_import.source_format or "").lower() == "platform"


def platform_import_hydration_complete(call_import: CallImport) -> bool:
    """True when evaluation may start on the rows discovered so far."""
    if not is_platform_call_import(call_import):
        return True
    from sqlalchemy.orm import object_session

    from app.services.call_imports.bulk_ops import _aggregate_import_row_status_counts

    db = object_session(call_import)
    if db is None:
        return False
    total, _completed, _failed, pending, processing = _aggregate_import_row_status_counts(
        db, call_import.id
    )
    if pending > 0 or processing > 0:
        return False
    discovery = (call_import.discovery_status or "").lower()
    if discovery in {"completed", "capped", "failed", "partial"}:
        return True
    # Recording hydrate is done for every listed row; do not block eval on a
    # stuck or slow last discovery window (listing can lag row downloads).
    return total > 0


def validate_diarised_eval_recording_ready(
    parameters: List[CallImportSchemaParameter],
    parameter_mapping: Dict[str, Any],
) -> None:
    rec_url_param = next(
        (
            p
            for p in parameters
            if p.type == CallImportParameterType.RECORDING_URL.value
        ),
        None,
    )
    if rec_url_param is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Diarize then evaluate requires a schema parameter of type "
                "'recording_url'. Add one to the schema and map it to a "
                "source column."
            ),
        )
    mapped_header = (parameter_mapping or {}).get(rec_url_param.name)
    if not (mapped_header or "").strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Diarize then evaluate requires the "
                f"'{rec_url_param.name}' recording URL parameter to be "
                "mapped to a source column."
            ),
        )


def resolve_telephony_integration(
    db: Session,
    organization_id: UUID,
    telephony_integration_id: UUID,
    provider: str,
) -> TelephonyIntegration:
    integration = (
        db.query(TelephonyIntegration)
        .filter(
            TelephonyIntegration.id == telephony_integration_id,
            TelephonyIntegration.organization_id == organization_id,
        )
        .first()
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telephony credential not found for this organization.",
        )
    if (integration.provider or "").lower() != provider.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Selected credential is for provider '{integration.provider}', "
                f"but request specified '{provider}'."
            ),
        )
    if not integration.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected telephony credential is inactive.",
        )
    return integration


def is_stuck_pending_import_row(row: CallImportRow) -> bool:
    if row.status != CallImportRowStatus.PENDING:
        return False
    if (row.attempts or 0) > 0:
        return True
    message = (row.error_message or "").lower()
    return any(marker in message for marker in STUCK_PENDING_ERROR_MARKERS)


def validate_telephony_credentials_live(
    db: Session,
    organization_id: UUID,
    integration: TelephonyIntegration,
) -> None:
    from app.services.telephony.telephony_service import telephony_service

    provider_label = (integration.provider or "telephony").title()
    try:
        client = telephony_service.get_provider_client(
            organization_id,
            db,
            provider=integration.provider,
            credential_id=integration.id,
        )
        client.test_connection()
    except HTTPException:
        raise
    except Exception as exc:
        detail = str(exc).strip() or "Unknown error"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{provider_label} credentials could not be verified: {detail}. "
                "Update credentials in Integrations and retry."
            ),
        ) from exc


def materialize_rows(
    db: Session,
    call_import: CallImport,
    parsed_rows: List[Dict[str, Any]],
    organization_id: UUID,
) -> List[CallImportRow]:
    row_models: List[CallImportRow] = []
    for idx, row in enumerate(parsed_rows):
        csv_transcript = row["transcript"]
        row_model = CallImportRow(
            call_import_id=call_import.id,
            organization_id=organization_id,
            workspace_id=call_import.workspace_id,
            row_index=idx,
            conversation_id=row["conversation_id"],
            recording_date=(
                _parse_recording_date_cell(row["recording_date"])
                if row.get("recording_date")
                else None
            ),
            recording_url=row["recording_url"],
            transcript=csv_transcript,
            transcript_source=(
                "csv" if csv_transcript and csv_transcript.strip() else None
            ),
            raw_columns=row["parameter_values"] or None,
            status=CallImportRowStatus.PENDING,
        )
        db.add(row_model)
        row_models.append(row_model)
    return row_models


def enqueue_row_tasks(
    db: Session,
    call_import: CallImport,
    row_models: List[CallImportRow],
) -> None:
    del db, call_import, row_models
    from app.workers.concurrency.fair_import_dispatch import (
        schedule_fair_import_dispatch,
    )

    schedule_fair_import_dispatch(max_workspace_turns=999)


def ensure_blob_storage_enabled() -> None:
    from app.services.storage.s3_service import s3_service

    if not s3_service.is_enabled():
        err = (
            s3_service.get_status_message()
            or "Cloud blob storage is not enabled or not configured"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Call uploads require cloud blob storage so the file can be "
                f"persisted between stages: {err}"
            ),
        )
