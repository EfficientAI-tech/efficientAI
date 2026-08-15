"""Throttled fan-out for call-import evaluation rows."""

from __future__ import annotations

from typing import Callable, List, Literal, NamedTuple, Optional
from uuid import UUID

from celery.utils import uuid as celery_uuid
from loguru import logger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.db_sharding.session_cache import ShardSessionCache
from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
)
from app.models.enums import CallImportRowStatus
from app.workers.concurrency.limits import (
    acquire_eval_slot,
    release_eval_slot_for_celery_task,
)
from app.workers.config import celery_app

IMPORTS_QUEUE = "imports"
DIARIZATION_QUEUE = "diarization"
EVALUATIONS_QUEUE = "evaluations"
AUDIO_METRICS_QUEUE = "audio-metrics"
# Lightweight scheduler tasks — runs on ``evaluations`` so sandbox/dev can use
# ``worker-imports`` (imports,diarization,evaluations) without a separate celery worker.
# Row scoring also uses ``evaluations``; dispatch tasks are short DB/Redis work.
DISPATCH_QUEUE = "evaluations"

DispatchSingleRowResult = Literal[
    "dispatched", "skip", "at_capacity", "credential_throttled"
]


class EvalDispatchOutcome(NamedTuple):
    result: DispatchSingleRowResult
    wait_seconds: int = 0


def schedule_evaluation_dispatch(
    evaluation_id: UUID | str,
    *,
    restricted_metric_ids: Optional[List[str]] = None,
    transcribe_overwrite: bool = False,
    auto_transcribe: bool = True,
    countdown: int = 0,
) -> None:
    """Schedule fair round-robin dispatch (evaluation_id kept for API compat)."""
    from app.workers.concurrency.fair_dispatch import schedule_fair_dispatch

    schedule_fair_dispatch(max_workspace_turns=999, countdown=countdown)


def _needs_transcribe_for_eval(
    evaluation: CallImportEvaluation,
    source_row: CallImportRow,
    *,
    transcribe_overwrite: bool,
    auto_transcribe: bool = True,
) -> bool:
    if (
        (getattr(evaluation, "transcript_source", None) or "")
        .strip()
        .lower()
        == "production"
    ):
        return False
    if not auto_transcribe:
        return False
    transcribe_mode = (
        getattr(evaluation, "transcribe_mode", None) or "stt_llm"
    ).strip().lower()
    has_stt_config = bool(evaluation.stt_provider and evaluation.stt_model)
    has_diariser_config = bool(
        getattr(evaluation, "diarisation_llm_provider", None)
        and getattr(evaluation, "diarisation_llm_model", None)
    )
    can_auto_transcribe = (
        has_stt_config if transcribe_mode == "stt_llm" else has_diariser_config
    )
    has_audio = bool((source_row.recording_s3_key or "").strip())
    existing_dia = (source_row.diarised_transcript or "").strip()
    needs_diarisation = not existing_dia or transcribe_overwrite
    return bool(can_auto_transcribe and has_audio and needs_diarisation)


def _diarisation_in_flight(source_row: CallImportRow) -> bool:
    """True when another worker is actively diarising this source row."""
    dia_status = (source_row.diarised_transcript_status or "").strip().lower()
    if dia_status not in {"pending", "running"}:
        return False
    return bool((source_row.celery_task_id or "").strip())


def _needs_import_for_eval(
    source_row: CallImportRow,
    evaluation: CallImportEvaluation | None = None,
) -> bool:
    """True when the eval pipeline must fetch a recording before later stages."""
    if evaluation is not None and (
        (getattr(evaluation, "transcript_source", None) or "")
        .strip()
        .lower()
        == "production"
    ):
        return False
    if source_row.status in (
        CallImportRowStatus.COMPLETED,
        CallImportRowStatus.FAILED,
        CallImportRowStatus.PROCESSING,
    ):
        return False
    if (source_row.recording_s3_key or "").strip():
        return False
    return bool((source_row.recording_url or "").strip())


def _fail_eval_row_for_import(
    db: Session,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
    *,
    catalog_db: Session | None = None,
    evaluation: CallImportEvaluation | None = None,
) -> None:
    from datetime import datetime, timezone

    from app.db_sharding.row_ops import commit_shard_row_session
    from app.workers.tasks.evaluate_call_import_row_core import (
        commit_terminal_row_and_rollup,
    )

    previous_status = eval_row.status or "pending"
    eval_row.status = "failed"
    eval_row.error_message = (
        source_row.error_message or "Recording fetch failed"
    )
    eval_row.finished_at = datetime.now(timezone.utc)
    eval_row.celery_task_id = None
    if evaluation is not None:
        commit_terminal_row_and_rollup(
            db,
            evaluation,
            eval_row,
            previous_row_status=previous_status,
            catalog_db=(
                catalog_db if catalog_db is not None and catalog_db is not db else None
            ),
        )
    else:
        commit_shard_row_session(db)


def source_row_import_blocks_eval(source_row: CallImportRow) -> bool:
    """True when import failure prevents the eval pipeline from continuing."""
    if (source_row.recording_s3_key or "").strip():
        return False
    return source_row.status == CallImportRowStatus.FAILED


def recover_eval_row_for_eval_chain(eval_row: CallImportEvaluationRow) -> None:
    """Undo a premature eval-row failure so the eval chain can continue."""
    from app.workers.tasks.evaluate_call_import_row_core import (
        EVAL_CANCELLED_BY_USER_ERROR,
    )

    if eval_row.status != "failed":
        return
    if (eval_row.error_message or "") == EVAL_CANCELLED_BY_USER_ERROR:
        return
    eval_row.status = "pending"
    eval_row.error_message = None
    eval_row.finished_at = None


def build_eval_chain_import_apply_async(
    *,
    source_row: CallImportRow,
    eval_row: CallImportEvaluationRow,
    reserved_task_id: str,
):
    """Build a Celery ``apply_async`` for eval-chain recording import."""
    from app.workers.tasks.process_call_import_row import (
        process_call_import_row_task,
    )

    return process_call_import_row_task.apply_async(
        args=(str(source_row.id),),
        kwargs={
            "_eval_slot_task_id": reserved_task_id,
            "run_eval_row_id": str(eval_row.id),
        },
        queue=IMPORTS_QUEUE,
        task_id=reserved_task_id,
    )


def build_eval_chain_transcribe_apply_async(
    *,
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
    reserved_task_id: str,
    restricted_metric_ids: Optional[List[str]] = None,
    transcribe_overwrite: bool = False,
):
    """Build a Celery ``apply_async`` for eval-chain diarisation."""
    from app.workers.tasks.transcribe_call_import_row import (
        transcribe_call_import_row_task,
    )

    transcribe_mode = (
        getattr(evaluation, "transcribe_mode", None) or "stt_llm"
    ).strip().lower()
    kwargs = {"_eval_slot_task_id": reserved_task_id}
    if restricted_metric_ids:
        kwargs["eval_restricted_metric_ids"] = restricted_metric_ids
    return transcribe_call_import_row_task.apply_async(
        args=(
            str(source_row.id),
            evaluation.stt_provider if transcribe_mode == "stt_llm" else None,
            evaluation.stt_model if transcribe_mode == "stt_llm" else None,
            str(evaluation.stt_credential_id)
            if transcribe_mode == "stt_llm" and evaluation.stt_credential_id
            else None,
            None,
            transcribe_overwrite,
            str(eval_row.id),
            getattr(evaluation, "diarisation_llm_provider", None),
            getattr(evaluation, "diarisation_llm_model", None),
            str(evaluation.diarisation_llm_credential_id)
            if getattr(evaluation, "diarisation_llm_credential_id", None)
            else None,
            getattr(evaluation, "diarisation_prompt", None),
            transcribe_mode,
        ),
        kwargs=kwargs,
        queue=DIARIZATION_QUEUE,
        task_id=reserved_task_id,
    )


def enqueue_eval_chain_transcribe_after_import(
    db: Session,
    *,
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
    slot_task_id: str,
    restricted_metric_ids: Optional[List[str]] = None,
    transcribe_overwrite: bool = False,
) -> bool:
    """Directly chain diarisation after a successful eval-chain recording fetch."""
    if not _needs_transcribe_for_eval(
        evaluation,
        source_row,
        transcribe_overwrite=transcribe_overwrite,
    ):
        return False

    from app.db_sharding.row_ops import shard_row_write_context

    recover_eval_row_for_eval_chain(eval_row)

    from app.workers.tasks.evaluate_call_import_row_core import (
        is_eval_row_user_cancelled,
    )

    if is_eval_row_user_cancelled(eval_row):
        return False

    with shard_row_write_context(db):
        source_row.diarised_transcript_status = "pending"
        source_row.diarised_transcript_error = None
        source_row.celery_task_id = slot_task_id
        eval_row.celery_task_id = None
        db.flush()

        async_result = build_eval_chain_transcribe_apply_async(
            evaluation=evaluation,
            eval_row=eval_row,
            source_row=source_row,
            reserved_task_id=slot_task_id,
            restricted_metric_ids=restricted_metric_ids,
            transcribe_overwrite=transcribe_overwrite,
        )
        eval_row.celery_task_id = async_result.id
        db.commit()
    return True


def _reserve_slot_and_enqueue(
    *,
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    db: Session,
    enqueue_fn: Callable[[str], object],
) -> bool:
    """Reserve a fair-share slot and enqueue a Celery task."""
    reserved_task_id = celery_uuid()
    if not acquire_eval_slot(
        workspace_id=evaluation.workspace_id,
        organization_id=evaluation.organization_id,
        celery_task_id=reserved_task_id,
        evaluation_id=evaluation.id,
    ):
        return False

    from app.db_sharding.row_ops import shard_row_write_context

    try:
        with shard_row_write_context(db):
            async_result = enqueue_fn(reserved_task_id)
            eval_row.celery_task_id = async_result.id
            db.commit()
    except Exception:
        release_eval_slot_for_celery_task(reserved_task_id)
        raise
    return True


def _attach_sharded_eval_dispatch_rows(
    catalog_db: Session,
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
    *,
    shard_cache: ShardSessionCache | None = None,
) -> tuple[Session, CallImportEvaluationRow, CallImportRow, bool] | None:
    """Bind eval/source rows on a shard session without extra catalog connections."""
    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.row_ops import shard_id_for_row
    from app.db_sharding.sessions import is_sharding_enabled

    if not is_sharding_enabled():
        return catalog_db, eval_row, source_row, False

    shard_id = shard_id_for_row(
        catalog_db,
        evaluation.call_import_id,
        int(source_row.row_index or 0),
    )
    owns_session = shard_cache is None
    if shard_cache is not None:
        shard_db = shard_cache.session_for(shard_id)
    else:
        shard_db = db_pool_manager.shard_session_factory(shard_id)()
    try:
        bound_eval = (
            shard_db.query(CallImportEvaluationRow)
            .filter(CallImportEvaluationRow.id == eval_row.id)
            .first()
        )
        bound_source = (
            shard_db.query(CallImportRow)
            .filter(CallImportRow.id == source_row.id)
            .first()
        )
        if bound_eval is None or bound_source is None:
            if owns_session:
                shard_db.close()
            return None
        if (bound_eval.status or "") != "pending" or bound_eval.celery_task_id:
            if owns_session:
                shard_db.close()
            return None
        return shard_db, bound_eval, bound_source, owns_session
    except Exception:
        if owns_session:
            shard_db.close()
        raise


def _load_call_import_for_eval_row(
    catalog_db: Session,
    source_row: CallImportRow,
) -> CallImport | None:
    call_import_id = source_row.call_import_id
    if call_import_id is None:
        return None
    return (
        catalog_db.query(CallImport)
        .filter(CallImport.id == call_import_id)
        .first()
    )


def _try_dispatch_single_row(
    *,
    db: Session,
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
    restricted_metric_ids: Optional[List[str]] = None,
    transcribe_overwrite: bool = False,
    auto_transcribe: bool = True,
    call_import: CallImport | None = None,
    shard_cache: ShardSessionCache | None = None,
) -> EvalDispatchOutcome:
    """Dispatch one eval row (transcribe or evaluate).

    Returns:
      * ``dispatched`` — task enqueued
      * ``skip`` — row not ready or evaluation terminal; try next row in batch
      * ``at_capacity`` — inflight cap reached; stop the workspace batch
      * ``credential_throttled`` — shared telephony credential is backing off
    """
    from app.db_sharding.sessions import is_sharding_enabled
    from app.workers.tasks.evaluate_call_import_row import (
        evaluate_call_import_row_task,
    )
    from app.workers.tasks.evaluate_call_import_row_audio import (
        evaluate_call_import_row_audio_task,
    )
    from app.workers.tasks.evaluate_call_import_row_core import (
        row_needs_audio_phase,
    )
    attached = _attach_sharded_eval_dispatch_rows(
        db,
        evaluation,
        eval_row,
        source_row,
        shard_cache=shard_cache,
    )
    if attached is None:
        return EvalDispatchOutcome("skip")

    mutate_db, eval_row, source_row, owns_shard_session = attached
    catalog_db = db

    try:
        if (evaluation.status or "").strip().lower() == "cancelled":
            return EvalDispatchOutcome("skip")

        from app.services.call_imports.evaluation_bulk_op import (
            get_evaluation_bulk_operation,
        )

        if get_evaluation_bulk_operation(evaluation.id):
            return EvalDispatchOutcome("skip")

        if source_row.status == CallImportRowStatus.FAILED:
            if source_row_import_blocks_eval(source_row):
                _fail_eval_row_for_import(
                    mutate_db,
                    eval_row,
                    source_row,
                    catalog_db=catalog_db,
                    evaluation=evaluation,
                )
                return EvalDispatchOutcome("skip")

        if source_row.status == CallImportRowStatus.PROCESSING:
            if not (source_row.recording_s3_key or "").strip():
                return EvalDispatchOutcome("skip")

        if _needs_import_for_eval(source_row, evaluation):
            from app.workers.concurrency.import_dispatch import (
                _peek_authenticated_import_credit,
            )

            call_import = call_import or _load_call_import_for_eval_row(
                catalog_db, source_row
            )
            if call_import is None:
                return EvalDispatchOutcome("skip")
            throttled = _peek_authenticated_import_credit(
                db=catalog_db,
                call_import=call_import,
            )
            if throttled is not None:
                return EvalDispatchOutcome(
                    "credential_throttled",
                    wait_seconds=throttled.wait_seconds,
                )

            def _enqueue_import(reserved_task_id: str):
                source_row.celery_task_id = reserved_task_id
                mutate_db.flush()
                return build_eval_chain_import_apply_async(
                    source_row=source_row,
                    eval_row=eval_row,
                    reserved_task_id=reserved_task_id,
                )

            if _reserve_slot_and_enqueue(
                evaluation=evaluation,
                eval_row=eval_row,
                db=mutate_db,
                enqueue_fn=_enqueue_import,
            ):
                return EvalDispatchOutcome("dispatched")
            return EvalDispatchOutcome("at_capacity")

        if _needs_transcribe_for_eval(
            evaluation,
            source_row,
            transcribe_overwrite=transcribe_overwrite,
            auto_transcribe=auto_transcribe,
        ):
            from app.workers.tasks.evaluate_call_import_row_core import (
                is_eval_row_user_cancelled,
            )

            if is_eval_row_user_cancelled(eval_row):
                return EvalDispatchOutcome("skip")

            if _diarisation_in_flight(source_row):
                return EvalDispatchOutcome("skip")

            dia_status = (
                source_row.diarised_transcript_status or ""
            ).strip().lower()
            if (
                dia_status == "failed"
                and not transcribe_overwrite
                and not (source_row.diarised_transcript or "").strip()
            ):
                return EvalDispatchOutcome("skip")

            def _enqueue_transcribe(reserved_task_id: str):
                source_row.diarised_transcript_status = "pending"
                source_row.diarised_transcript_error = None
                if transcribe_overwrite:
                    source_row.diarised_transcript = None
                source_row.celery_task_id = reserved_task_id
                mutate_db.flush()
                return build_eval_chain_transcribe_apply_async(
                    evaluation=evaluation,
                    eval_row=eval_row,
                    source_row=source_row,
                    reserved_task_id=reserved_task_id,
                    restricted_metric_ids=restricted_metric_ids,
                    transcribe_overwrite=transcribe_overwrite,
                )

            if _reserve_slot_and_enqueue(
                evaluation=evaluation,
                eval_row=eval_row,
                db=mutate_db,
                enqueue_fn=_enqueue_transcribe,
            ):
                return EvalDispatchOutcome("dispatched")
            return EvalDispatchOutcome("at_capacity")

        if row_needs_audio_phase(
            catalog_db,
            evaluation,
            source_row,
            restricted_metric_ids=restricted_metric_ids,
        ):

            def _enqueue_audio(reserved_task_id: str):
                kwargs = {"_eval_slot_task_id": reserved_task_id}
                if restricted_metric_ids:
                    kwargs["restricted_metric_ids"] = restricted_metric_ids
                return evaluate_call_import_row_audio_task.apply_async(
                    args=(str(eval_row.id),),
                    kwargs=kwargs,
                    queue=AUDIO_METRICS_QUEUE,
                    task_id=reserved_task_id,
                )

            if _reserve_slot_and_enqueue(
                evaluation=evaluation,
                eval_row=eval_row,
                db=mutate_db,
                enqueue_fn=_enqueue_audio,
            ):
                return EvalDispatchOutcome("dispatched")
            return EvalDispatchOutcome("at_capacity")

        def _enqueue_eval(reserved_task_id: str):
            kwargs = {"_eval_slot_task_id": reserved_task_id}
            if restricted_metric_ids:
                kwargs["restricted_metric_ids"] = restricted_metric_ids
            return evaluate_call_import_row_task.apply_async(
                args=(str(eval_row.id),),
                kwargs=kwargs,
                queue=EVALUATIONS_QUEUE,
                task_id=reserved_task_id,
            )

        if _reserve_slot_and_enqueue(
            evaluation=evaluation,
            eval_row=eval_row,
            db=mutate_db,
            enqueue_fn=_enqueue_eval,
        ):
            return EvalDispatchOutcome("dispatched")
        return EvalDispatchOutcome("at_capacity")
    finally:
        if owns_shard_session and is_sharding_enabled() and mutate_db is not db:
            mutate_db.close()


@celery_app.task(name="dispatch_evaluation_rows", queue=EVALUATIONS_QUEUE)
def dispatch_evaluation_rows_task(
    evaluation_id: str,
    restricted_metric_ids: Optional[List[str]] = None,
    transcribe_overwrite: bool = False,
    auto_transcribe: bool = True,
) -> dict:
    """Legacy per-evaluation dispatcher — delegates to fair round-robin."""
    schedule_evaluation_dispatch(
        evaluation_id,
        restricted_metric_ids=restricted_metric_ids,
        transcribe_overwrite=transcribe_overwrite,
        auto_transcribe=auto_transcribe,
    )
    return {"status": "delegated", "dispatcher": "fair", "evaluation_id": evaluation_id}
