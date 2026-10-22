"""Celery task: audio-metric phase for call-import evaluation rows.

Runs on the ``audio-metrics`` queue (``worker`` service) so torch/Praat/UTMOS
stay off the lightweight ``worker-imports`` pool.
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from loguru import logger

from app.models.database import CallImportEvaluation
from app.workers.config import celery_app
from app.workers.concurrency.eval_dispatch import EVALUATIONS_QUEUE
from app.workers.tasks.evaluate_call_import_row_core import (
    as_json_dict,
    categorize_row_metrics,
    load_enabled_metrics,
    now_utc,
    parse_restricted_metric_uuids,
    rollup_parent,
    claim_eval_row_for_task,
    commit_terminal_row_and_rollup,
    row_needs_llm_phase,
    was_cancelled_externally,
)


def _rollup_terminal(row_db, catalog_db, evaluation, eval_row, *, previous_row_status):
    cat = catalog_db if catalog_db is not row_db else None
    commit_terminal_row_and_rollup(
        row_db,
        evaluation,
        eval_row,
        previous_row_status=previous_row_status,
        catalog_db=cat,
    )


def _persist_sessions(row_db, catalog_db) -> None:
    row_db.commit()
    if catalog_db is not row_db:
        catalog_db.commit()


_CHAIN_TTL_SECONDS = 7200
_PUBLISH_LOCK_SECONDS = 60
_PUBLISH_ATTEMPTS = 8


def _chain_key(eval_row_id: str) -> str:
    return f"eval:audio-chain:{eval_row_id}"


def _publish_lock_key(chained_task_id: str) -> str:
    return f"eval:audio-chain-publish:{chained_task_id}"


def _read_audio_chain(eval_row_id: str, audio_task_id: str) -> tuple[str, str] | None:
    """Handoff for this audio task only. A later retry has a different task id."""
    try:
        from app.workers.concurrency.limits import _get_redis

        raw = _get_redis().get(_chain_key(eval_row_id))
    except Exception:
        return None
    text = raw.decode() if isinstance(raw, bytes) else str(raw or "")
    state, sep, rest = text.partition(":")
    owner, sep2, chained_task_id = rest.partition(":")
    if (
        sep != ":"
        or sep2 != ":"
        or state not in {"reserved", "published"}
        or owner != (audio_task_id or "").strip()
        or not chained_task_id
    ):
        return None
    return state, chained_task_id


def _write_audio_chain(
    eval_row_id: str, state: str, audio_task_id: str, chained_task_id: str
) -> None:
    try:
        from app.workers.concurrency.limits import _get_redis

        _get_redis().set(
            _chain_key(eval_row_id),
            f"{state}:{audio_task_id}:{chained_task_id}",
            ex=_CHAIN_TTL_SECONDS,
        )
    except Exception:
        logger.warning("audio chain marker write failed for {}", eval_row_id)


def _chained_task_id_from_marker(raw) -> str:
    text = raw.decode() if isinstance(raw, bytes) else str(raw or "")
    _state, _sep, rest = text.partition(":")
    _owner, _sep2, chained_task_id = rest.partition(":")
    return chained_task_id


def clear_eval_audio_chain(eval_row_id: str) -> None:
    """Drop a handoff so a new attempt cannot reuse it."""
    clear_eval_audio_chains([eval_row_id])


def clear_eval_audio_chains(eval_row_ids: List[str]) -> None:
    """Pipeline chain deletes for one retry page."""
    ids = [row_id for row_id in eval_row_ids if row_id]
    if not ids:
        return
    try:
        from app.workers.concurrency.limits import _get_redis

        client = _get_redis()
        keys = [_chain_key(row_id) for row_id in ids]
        pipe = client.pipeline()
        for key in keys:
            pipe.get(key)
        values = pipe.execute()
        pipe = client.pipeline()
        for key, raw in zip(keys, values):
            chained_task_id = _chained_task_id_from_marker(raw)
            if chained_task_id:
                pipe.delete(_publish_lock_key(chained_task_id))
            pipe.delete(key)
        pipe.execute()
    except Exception:
        return


def _claim_chain_publish(chained_task_id: str) -> bool | None:
    """True if this caller may publish. False if a publish is in progress."""
    try:
        from app.workers.concurrency.limits import _get_redis

        acquired = _get_redis().set(
            _publish_lock_key(chained_task_id),
            "1",
            nx=True,
            ex=_PUBLISH_LOCK_SECONDS,
        )
    except Exception:
        logger.warning("audio chain publish lock failed for {}", chained_task_id)
        return None
    return bool(acquired)


def _release_chain_publish(chained_task_id: str) -> None:
    try:
        from app.workers.concurrency.limits import _get_redis

        _get_redis().delete(_publish_lock_key(chained_task_id))
    except Exception:
        return


def _llm_task_is_queued(
    eval_row_id: str, audio_task_id: str, chained_task_id: str
) -> bool:
    fresh = _read_audio_chain(eval_row_id, audio_task_id)
    return bool(fresh and fresh[0] == "published" and fresh[1] == chained_task_id)


def _publish_chained_llm(
    *,
    eval_row_id: str,
    audio_task_id: str,
    chained_task_id: str,
    predecessor_task_id: str,
    slot_task_id: str | None,
    restricted_metric_ids: Optional[List[str]],
) -> bool:
    """Queue the LLM task once.

    True only when this call queued it, or the published marker already
    proves an earlier call did. A lock with no marker is an unfinished
    publish, not proof the task was queued.
    """
    from app.workers.tasks.evaluate_call_import_row import (
        evaluate_call_import_row_task,
    )

    acquired = _claim_chain_publish(chained_task_id)
    if acquired is not True:
        return _llm_task_is_queued(eval_row_id, audio_task_id, chained_task_id)
    chain_kwargs: dict = {
        "_skip_audio": True,
        "_eval_slot_task_id": slot_task_id,
        "_predecessor_task_id": predecessor_task_id,
    }
    if restricted_metric_ids:
        chain_kwargs["restricted_metric_ids"] = restricted_metric_ids
    try:
        evaluate_call_import_row_task.apply_async(
            args=(str(eval_row_id),),
            kwargs=chain_kwargs,
            queue=EVALUATIONS_QUEUE,
            task_id=chained_task_id,
        )
    except Exception:
        _release_chain_publish(chained_task_id)
        raise
    _write_audio_chain(eval_row_id, "published", audio_task_id, chained_task_id)
    return True


def _retry_unfinished_publish(task) -> bool:
    """Come back after the in-progress lock. False when retries are exhausted."""
    from celery.exceptions import MaxRetriesExceededError

    try:
        task.retry(countdown=_PUBLISH_LOCK_SECONDS, max_retries=_PUBLISH_ATTEMPTS)
    except MaxRetriesExceededError:
        return False
    return False


@celery_app.task(
    name="evaluate_call_import_row_audio",
    bind=True,
    max_retries=2,
    time_limit=10 * 60,
    soft_time_limit=8 * 60,
)
def evaluate_call_import_row_audio_task(
    self,
    eval_row_id: str,
    restricted_metric_ids: Optional[List[str]] = None,
    _eval_slot_task_id: Optional[str] = None,
):
    """Score audio-only metrics; chain LLM phase or finalize when done."""
    from app.db_sharding.eval_rows import evaluation_row_session

    slot_task_id = _eval_slot_task_id or self.request.id
    chain_llm = False
    keep_slot = False
    try:
        with evaluation_row_session(eval_row_id) as (
            row_db,
            catalog_db,
            eval_row,
            source_row,
            _shard_id,
        ):
            from app.workers.tasks.evaluate_call_import_row_core import (
                load_evaluation_for_worker,
            )

            evaluation = load_evaluation_for_worker(
                catalog_db, eval_row.evaluation_id
            )
            if not evaluation:
                eval_row.status = "failed"
                eval_row.error_message = "Evaluation parent not found"
                row_db.commit()
                return {"status": "failed", "reason": "evaluation_missing"}

            mine = str(self.request.id or "")
            chain_state = _read_audio_chain(eval_row_id, mine)
            owner = (eval_row.celery_task_id or "").strip()
            if chain_state and chain_state[0] == "published":
                if owner != chain_state[1] and (eval_row.status or "") in {
                    "pending",
                    "running",
                }:
                    eval_row.celery_task_id = chain_state[1]
                    row_db.commit()
                chain_llm = True
                return {
                    "status": "chained",
                    "eval_row_id": eval_row_id,
                    "next": "llm_phase",
                }
            if (
                chain_state
                and chain_state[0] == "reserved"
                and (eval_row.status or "") in {"pending", "running"}
                and owner in {"", mine, chain_state[1]}
            ):
                try:
                    queued = _publish_chained_llm(
                        eval_row_id=eval_row_id,
                        audio_task_id=mine,
                        chained_task_id=chain_state[1],
                        predecessor_task_id=mine,
                        slot_task_id=slot_task_id,
                        restricted_metric_ids=restricted_metric_ids,
                    )
                except Exception:
                    logger.exception(
                        "[CallImportEval {}] Failed to enqueue LLM phase",
                        eval_row.id,
                    )
                    clear_eval_audio_chain(eval_row_id)
                    eval_row.status = "failed"
                    eval_row.error_message = "Failed to enqueue LLM evaluation phase"
                    eval_row.finished_at = now_utc()
                    _rollup_terminal(
                        row_db,
                        catalog_db,
                        evaluation,
                        eval_row,
                        previous_row_status="running",
                    )
                    return {
                        "status": "failed",
                        "eval_row_id": eval_row_id,
                        "reason": "chain_enqueue_failed",
                    }
                if not queued:
                    keep_slot = True
                    if not _retry_unfinished_publish(self):
                        keep_slot = False
                        clear_eval_audio_chain(eval_row_id)
                        eval_row.status = "failed"
                        eval_row.error_message = "Failed to enqueue LLM evaluation phase"
                        eval_row.finished_at = now_utc()
                        _rollup_terminal(
                            row_db,
                            catalog_db,
                            evaluation,
                            eval_row,
                            previous_row_status="running",
                        )
                        return {
                            "status": "failed",
                            "eval_row_id": eval_row_id,
                            "reason": "chain_enqueue_failed",
                        }
                eval_row.celery_task_id = chain_state[1]
                chain_llm = True
                row_db.commit()
                return {
                    "status": "chained",
                    "eval_row_id": eval_row_id,
                    "next": "llm_phase",
                }

            if not claim_eval_row_for_task(row_db, eval_row, self.request.id):
                logger.info(
                    "Skipping audio eval row {} already claimed or finished",
                    eval_row_id,
                )
                return {"status": "skipped", "reason": "already_claimed"}

            previous_row_status = "running"
            if evaluation.status == "pending":
                evaluation.status = "running"
                evaluation.started_at = evaluation.started_at or now_utc()
                catalog_db.commit()

            restricted_uuids = parse_restricted_metric_uuids(restricted_metric_ids)
            if restricted_metric_ids is not None and restricted_uuids is not None:
                selected_raw = {str(x) for x in (evaluation.selected_metric_ids or [])}
                if restricted_uuids and not any(
                    str(mid) in selected_raw for mid in restricted_uuids
                ):
                    eval_row.status = "completed"
                    eval_row.error_message = None
                    eval_row.finished_at = now_utc()
                    _rollup_terminal(
                        row_db,
                        catalog_db,
                        evaluation,
                        eval_row,
                        previous_row_status=previous_row_status,
                    )
                    return {
                        "status": "skipped",
                        "reason": "restricted_metric_ids_no_match",
                    }

            metrics = load_enabled_metrics(
                catalog_db, evaluation, restricted_metric_ids=restricted_metric_ids
            )
            if not metrics:
                eval_row.status = "failed"
                eval_row.error_message = "No enabled metrics selected for this evaluation"
                eval_row.finished_at = now_utc()
                _rollup_terminal(
                    row_db,
                    catalog_db,
                    evaluation,
                    eval_row,
                    previous_row_status=previous_row_status,
                )
                return {"status": "failed", "reason": "no_metrics"}

            (
                _transcript_metrics,
                audio_metrics,
                _comparison_metrics,
                metric_scores,
            ) = categorize_row_metrics(catalog_db, evaluation, source_row, metrics)

            recording_s3_key = (source_row.recording_s3_key or "").strip() or None
            result_id = f"call-import-eval:{eval_row.id}"
            audio_failed = False

            audio_seconds_for_billing = 0
            if recording_s3_key:
                from app.workers.tasks.evaluate_call_import_row_core import (
                    get_cached_eval_row_audio_seconds,
                    resolve_eval_row_audio_seconds,
                )

                resolve_eval_row_audio_seconds(catalog_db, eval_row, source_row)
                audio_seconds_for_billing = get_cached_eval_row_audio_seconds(eval_row)

            if audio_metrics and recording_s3_key:
                from types import SimpleNamespace

                from app.db_sharding.eval_rows import rebind_evaluation_row_session
                from app.db_sharding.row_ops import (
                    close_row_sessions,
                    locate_call_import_evaluation_row,
                )
                from app.workers.tasks.helpers.audio_evaluation import (
                    evaluate_audio_metrics,
                    handle_audio_evaluation_error,
                )
                from app.workers.tasks.helpers.score_utils import get_metric_type_value

                audio_inputs = [
                    SimpleNamespace(
                        id=metric.id,
                        name=metric.name,
                        metric_type=get_metric_type_value(metric),
                    )
                    for metric in audio_metrics
                ]
                eval_row_key = eval_row.id
                origin_row_db = row_db
                close_row_sessions(row_db, catalog_db)
                rebind_evaluation_row_session(origin_row_db, None, None)
                try:
                    audio_scores = evaluate_audio_metrics(
                        audio_s3_key=recording_s3_key,
                        audio_metrics=audio_inputs,
                        result_id=result_id,
                    )
                    metric_scores.update(audio_scores)
                except Exception as audio_err:  # noqa: BLE001
                    logger.exception(
                        "[CallImportEval {}] Audio analysis failed", eval_row_key
                    )
                    metric_scores.update(
                        handle_audio_evaluation_error(audio_inputs, audio_err)
                    )
                    audio_failed = True
                row_db, catalog_db, eval_row, source_row, _shard_id = (
                    locate_call_import_evaluation_row(
                        eval_row_key, shard_id=_shard_id
                    )
                )
                rebind_evaluation_row_session(origin_row_db, row_db, catalog_db)
                from app.workers.tasks.evaluate_call_import_row_core import (
                    load_evaluation_for_worker,
                )

                evaluation = load_evaluation_for_worker(
                    catalog_db, eval_row.evaluation_id
                )
                if evaluation is None:
                    return {"status": "failed", "reason": "evaluation_missing"}

            if was_cancelled_externally(row_db, eval_row):
                try:
                    rollup_parent(
                        catalog_db,
                        evaluation,
                        previous_row_status="running",
                        new_row_status="failed",
                    )
                    catalog_db.commit()
                except Exception:  # noqa: BLE001
                    catalog_db.rollback()
                return {"status": "cancelled", "eval_row_id": eval_row_id}

            existing = (
                eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
            )
            merged = dict(existing)
            for key, value in as_json_dict(metric_scores).items():
                merged[key] = value
            eval_row.metric_scores = merged
            if audio_seconds_for_billing > 0:
                from app.workers.tasks.evaluate_call_import_row_core import (
                    cache_eval_row_audio_seconds,
                )

                cache_eval_row_audio_seconds(eval_row, audio_seconds_for_billing)
            row_db.commit()

            needs_llm = row_needs_llm_phase(
                catalog_db,
                evaluation,
                source_row,
                restricted_metric_ids=restricted_metric_ids,
            )

            if needs_llm:
                from uuid import uuid4

                mine = str(self.request.id or "")
                chain_state = _read_audio_chain(eval_row_id, mine)
                if chain_state:
                    chained_task_id = chain_state[1]
                else:
                    chained_task_id = str(uuid4())
                    _write_audio_chain(
                        eval_row_id, "reserved", mine, chained_task_id
                    )
                if not chain_state or chain_state[0] == "reserved":
                    try:
                        queued = _publish_chained_llm(
                            eval_row_id=str(eval_row.id),
                            audio_task_id=mine,
                            chained_task_id=chained_task_id,
                            predecessor_task_id=mine,
                            slot_task_id=slot_task_id,
                            restricted_metric_ids=restricted_metric_ids,
                        )
                    except Exception:
                        logger.exception(
                            "[CallImportEval {}] Failed to enqueue LLM phase",
                            eval_row.id,
                        )
                        clear_eval_audio_chain(eval_row_id)
                        eval_row.status = "failed"
                        eval_row.error_message = "Failed to enqueue LLM evaluation phase"
                        eval_row.finished_at = now_utc()
                        _rollup_terminal(
                            row_db,
                            catalog_db,
                            evaluation,
                            eval_row,
                            previous_row_status=previous_row_status,
                        )
                        return {
                            "status": "failed",
                            "eval_row_id": eval_row_id,
                            "reason": "chain_enqueue_failed",
                        }
                    if not queued:
                        keep_slot = True
                        if not _retry_unfinished_publish(self):
                            keep_slot = False
                            clear_eval_audio_chain(eval_row_id)
                            eval_row.status = "failed"
                            eval_row.error_message = "Failed to enqueue LLM evaluation phase"
                            eval_row.finished_at = now_utc()
                            _rollup_terminal(
                                row_db,
                                catalog_db,
                                evaluation,
                                eval_row,
                                previous_row_status=previous_row_status,
                            )
                            return {
                                "status": "failed",
                                "eval_row_id": eval_row_id,
                                "reason": "chain_enqueue_failed",
                            }
                eval_row.celery_task_id = chained_task_id
                chain_llm = True
                row_db.commit()
                return {
                    "status": "chained",
                    "eval_row_id": eval_row_id,
                    "next": "llm_phase",
                }

            if audio_failed:
                eval_row.status = "failed"
                eval_row.error_message = "Evaluation failed for one or more audio metrics"
            else:
                eval_row.status = "completed"
                eval_row.error_message = None

            eval_row.finished_at = now_utc()
            _rollup_terminal(
                row_db,
                catalog_db,
                evaluation,
                eval_row,
                previous_row_status=previous_row_status,
            )

            return {
                "status": eval_row.status,
                "eval_row_id": eval_row_id,
                "phase": "audio_only",
            }
    except LookupError:
        logger.warning(
            "[CallImportEval audio {}] Row not found on any shard — skipping",
            eval_row_id,
        )
        return {"status": "skipped", "reason": "row_not_found"}
    finally:
        if not chain_llm and not keep_slot:
            from app.workers.concurrency.fair_dispatch import (
                finish_eval_work_and_redispatch,
            )

            finish_eval_work_and_redispatch(
                slot_task_id,
                restricted_metric_ids=restricted_metric_ids,
            )
