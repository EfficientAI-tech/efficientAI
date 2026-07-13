"""Throttled fan-out for standalone call-import diarization rows."""

from __future__ import annotations

import json
from typing import Literal, Optional, TypedDict
from uuid import UUID

import redis
from celery.utils import uuid as celery_uuid
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import CallImport, CallImportRow
from app.workers.concurrency.eval_dispatch import DIARIZATION_QUEUE
from app.workers.concurrency.limits import (
    acquire_eval_slot,
    release_eval_slot_for_celery_task,
)

_PENDING_PARAMS_KEY_PREFIX = "diarisation:pending:params:"
_PENDING_PARAMS_TTL_SECONDS = 20 * 60

_redis_client: redis.Redis | None = None

DispatchDiarizationRowResult = Literal["dispatched", "skip", "at_capacity"]


class DiarizationRowParams(TypedDict, total=False):
    stt_provider: Optional[str]
    stt_model: Optional[str]
    credential_id: Optional[str]
    language: Optional[str]
    overwrite_existing: bool
    diarization_llm_provider: Optional[str]
    diarization_llm_model: Optional[str]
    diarization_llm_credential_id: Optional[str]
    diarization_prompt: Optional[str]
    mode: str


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _pending_params_key(row_id: UUID | str) -> str:
    return f"{_PENDING_PARAMS_KEY_PREFIX}{row_id}"


def store_row_diarization_params(
    row_id: UUID | str,
    params: DiarizationRowParams,
) -> None:
    """Persist transcribe kwargs until the fair dispatcher enqueues the row."""
    key = _pending_params_key(row_id)
    try:
        _get_redis().setex(
            key,
            _PENDING_PARAMS_TTL_SECONDS,
            json.dumps(params),
        )
    except redis.RedisError as exc:
        logger.warning(
            "Failed to store diarization params for row {}: {}",
            row_id,
            exc,
        )


def get_row_diarization_params(row_id: UUID | str) -> Optional[DiarizationRowParams]:
    key = _pending_params_key(row_id)
    try:
        raw = _get_redis().get(key)
        if not raw:
            return None
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed  # type: ignore[return-value]
    except (redis.RedisError, json.JSONDecodeError) as exc:
        logger.warning(
            "Failed to read diarization params for row {}: {}",
            row_id,
            exc,
        )
    return None


def clear_row_diarization_params(row_id: UUID | str) -> None:
    key = _pending_params_key(row_id)
    try:
        _get_redis().delete(key)
    except redis.RedisError as exc:
        logger.warning(
            "Failed to clear diarization params for row {}: {}",
            row_id,
            exc,
        )


def pop_row_diarization_params(row_id: UUID | str) -> Optional[DiarizationRowParams]:
    params = get_row_diarization_params(row_id)
    if params is not None:
        clear_row_diarization_params(row_id)
    return params


def build_diarization_params_from_request(
    *,
    stt_provider: Optional[str],
    stt_model: Optional[str],
    credential_id: Optional[UUID | str],
    language: Optional[str],
    overwrite_existing: bool,
    diarization_llm_provider: Optional[str],
    diarization_llm_model: Optional[str],
    diarization_llm_credential_id: Optional[UUID | str],
    diarization_prompt: Optional[str],
    mode: str,
) -> DiarizationRowParams:
    return {
        "stt_provider": stt_provider,
        "stt_model": stt_model,
        "credential_id": str(credential_id) if credential_id else None,
        "language": language,
        "overwrite_existing": overwrite_existing,
        "diarization_llm_provider": diarization_llm_provider,
        "diarization_llm_model": diarization_llm_model,
        "diarization_llm_credential_id": (
            str(diarization_llm_credential_id)
            if diarization_llm_credential_id
            else None
        ),
        "diarization_prompt": diarization_prompt,
        "mode": mode,
    }


def _try_dispatch_single_diarization_row(
    *,
    db: Session,
    row: CallImportRow,
    call_import: CallImport,
    params: DiarizationRowParams,
) -> DispatchDiarizationRowResult:
    from app.workers.tasks.transcribe_call_import_row import (
        transcribe_call_import_row_task,
    )

    if (row.diarised_transcript_status or "").strip().lower() != "pending":
        return "skip"
    if row.celery_task_id:
        return "skip"

    reserved_task_id = celery_uuid()
    if not acquire_eval_slot(
        workspace_id=call_import.workspace_id,
        organization_id=call_import.organization_id,
        celery_task_id=reserved_task_id,
    ):
        return "at_capacity"

    try:
        async_result = transcribe_call_import_row_task.apply_async(
            args=(
                str(row.id),
                params.get("stt_provider"),
                params.get("stt_model"),
                params.get("credential_id"),
                params.get("language"),
                bool(params.get("overwrite_existing", False)),
                None,
                params.get("diarization_llm_provider"),
                params.get("diarization_llm_model"),
                params.get("diarization_llm_credential_id"),
                params.get("diarization_prompt"),
                params.get("mode") or "stt_llm",
            ),
            kwargs={"_eval_slot_task_id": reserved_task_id},
            queue=DIARIZATION_QUEUE,
            task_id=reserved_task_id,
        )
    except Exception:
        release_eval_slot_for_celery_task(reserved_task_id)
        raise

    try:
        row.celery_task_id = async_result.id
        db.commit()
    except Exception:
        release_eval_slot_for_celery_task(reserved_task_id)
        raise

    return "dispatched"
