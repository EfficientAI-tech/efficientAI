"""Flush Redis-buffered evaluation progress counters into the catalog.

Each tick:

1. Drain every dirty evaluation into its Redis pending slot (or reuse a
   pending slot left by a failed/crashed earlier tick, same ``seq``).
2. Apply all pending slots in one ``UPDATE ... FROM (VALUES ...)`` guarded by
   ``progress_counter_gen = gen AND progress_flush_seq < seq``, one commit.
3. Commit succeeded: acknowledge every slot, whatever the row count. A 0-row
   match means a recount superseded the batch or it was already applied;
   both are correct outcomes and must not be restored.
   Commit raised: leave the slots; the next tick re-sends the same payload.
4. Safety nets: request finalize when ``remaining <= 0``, when the hash had
   to be recreated (``uninit``), or when Redis' gen is ahead of the catalog
   (a recount's transaction rolled back).

Every ``EVAL_PROGRESS_RECOUNT_SECONDS`` it also sweeps running evaluations
from the *catalog* (not the dirty set) and requests a finalize/recount for
any not recounted recently, which catches idle runs whose last decrement or
finalize trigger was lost.
"""

from __future__ import annotations

import time
from typing import Iterable
from uuid import UUID

import redis
from loguru import logger
from sqlalchemy import and_, case, or_, text, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import CallImportEvaluation
from app.services.call_imports import eval_progress_buffer as buf
from app.workers.config import EVAL_CONTROL_QUEUE, celery_app

_FLUSHER_LOCK_KEY = "eval:ctr:flusher"
_SWEEP_GATE_KEY = "eval:ctr:sweep"
_VALUES_CHUNK = 500
_SWEEP_LIMIT = 500


def _apply_batch_postgres(db: Session, batch: list[tuple[UUID, buf.DrainResult]]) -> set[UUID]:
    matched: set[UUID] = set()
    for start in range(0, len(batch), _VALUES_CHUNK):
        chunk = batch[start : start + _VALUES_CHUNK]
        params: dict = {}
        rows_sql: list[str] = []
        for i, (eid, drained) in enumerate(chunk):
            rows_sql.append(
                f"(CAST(:id{i} AS uuid), CAST(:dc{i} AS integer), CAST(:df{i} AS integer), "
                f"CAST(:gen{i} AS integer), CAST(:seq{i} AS bigint))"
            )
            params[f"id{i}"] = str(eid)
            params[f"dc{i}"] = drained.completed_delta
            params[f"df{i}"] = drained.failed_delta
            params[f"gen{i}"] = drained.gen
            params[f"seq{i}"] = drained.seq
        statement = text(
            f"""
            UPDATE call_import_evaluations AS e SET
              completed_rows     = GREATEST(0, e.completed_rows + v.dc),
              failed_rows        = GREATEST(0, e.failed_rows + v.df),
              progress_flush_seq = v.seq,
              updated_at         = now()
            FROM (VALUES {", ".join(rows_sql)}) AS v(id, dc, df, gen, seq)
            WHERE e.id = v.id
              AND e.progress_counter_gen = v.gen
              AND e.progress_flush_seq < v.seq
            RETURNING e.id
            """
        )
        for (eid,) in db.execute(statement, params):
            matched.add(eid if isinstance(eid, UUID) else UUID(str(eid)))
    return matched


def _non_negative(expr):
    return case((expr < 0, 0), else_=expr)


def _apply_batch_generic(db: Session, batch: list[tuple[UUID, buf.DrainResult]]) -> set[UUID]:
    """Same guarded update, one statement per evaluation (SQLite / tests)."""
    matched: set[UUID] = set()
    for eid, drained in batch:
        result = db.execute(
            update(CallImportEvaluation)
            .where(
                CallImportEvaluation.id == eid,
                CallImportEvaluation.progress_counter_gen == drained.gen,
                CallImportEvaluation.progress_flush_seq < drained.seq,
            )
            .values(
                completed_rows=_non_negative(
                    CallImportEvaluation.completed_rows + drained.completed_delta
                ),
                failed_rows=_non_negative(
                    CallImportEvaluation.failed_rows + drained.failed_delta
                ),
                progress_flush_seq=drained.seq,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount:
            matched.add(eid)
    return matched


def apply_flush_batch(db: Session, batch: list[tuple[UUID, buf.DrainResult]]) -> set[UUID]:
    """Apply drained slots; returns evaluation ids whose row matched."""
    if not batch:
        return set()
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        return _apply_batch_postgres(db, batch)
    return _apply_batch_generic(db, batch)


def _parse_ids(raw_ids: Iterable[str]) -> list[UUID]:
    parsed: list[UUID] = []
    for raw in raw_ids:
        try:
            parsed.append(UUID(str(raw)))
        except (TypeError, ValueError):
            logger.warning("dropping malformed eval counter dirty member {!r}", raw)
            try:
                buf._client().srem(buf.DIRTY_SET_KEY, raw)
            except redis.RedisError:
                pass
    return parsed


def flush_eval_progress_counters(db: Session) -> dict:
    """One flush tick. Safe to run concurrently with workers and recounts."""
    stats = {"drained": 0, "applied": 0, "stale": 0, "finalize": 0, "failed": False}
    try:
        dirty = _parse_ids(buf.dirty_evaluation_ids())
    except redis.RedisError as exc:
        logger.warning("eval progress flush skipped (redis unavailable): {}", exc)
        return stats

    batch: list[tuple[UUID, buf.DrainResult]] = []
    tokens: dict[UUID, str] = {}
    finalize: set[UUID] = set()
    try:
        for eid in dirty:
            token = buf.acquire_lock(eid)
            if token is None:
                continue  # a fenced recount owns this evaluation right now
            tokens[eid] = token
            try:
                drained = buf.drain(eid)
            except redis.RedisError as exc:
                logger.warning("eval counter drain failed for {}: {}", eid, exc)
                continue
            if drained.kind == "uninit":
                finalize.add(eid)
                continue
            if drained.kind == "pending":
                batch.append((eid, drained))
            if drained.kind in ("pending", "empty") and drained.remaining <= 0:
                finalize.add(eid)
        stats["drained"] = len(batch)

        if batch:
            try:
                matched = apply_flush_batch(db, batch)
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                stats["failed"] = True
                # Pending slots stay in Redis; the next tick re-sends them
                # with the same seq, which the catalog guard makes idempotent.
                logger.warning(
                    "eval progress catalog flush failed for {} evaluations: {}",
                    len(batch),
                    exc,
                )
                return stats

            stats["applied"] = len(matched)
            unmatched = [(eid, drained) for eid, drained in batch if eid not in matched]
            stats["stale"] = len(unmatched)
            _inspect_unmatched(db, unmatched, finalize)
            for eid, drained in batch:
                try:
                    buf.ack(eid, drained.seq)
                except redis.RedisError as exc:
                    # Re-sent next tick; the seq guard makes that a no-op.
                    logger.debug("eval counter ack failed for {}: {}", eid, exc)
    finally:
        for eid, token in tokens.items():
            buf.release_lock(eid, token)

    for eid in finalize:
        if buf.request_finalize(eid):
            stats["finalize"] += 1
    return stats


def _inspect_unmatched(
    db: Session,
    unmatched: list[tuple[UUID, buf.DrainResult]],
    finalize: set[UUID],
) -> None:
    """Classify batches whose guarded UPDATE matched no row.

    * row gone: evaluation deleted, drop the Redis state.
    * catalog gen < batch gen: Redis was fenced by a recount whose catalog
      transaction rolled back. Request a recount so both sides agree again.
    * otherwise (newer gen, or seq already applied): stale, ack and drop.
    """
    if not unmatched:
        return
    ids = [eid for eid, _ in unmatched]
    catalog = {
        row[0]: (int(row[1] or 0), int(row[2] or 0))
        for row in db.query(
            CallImportEvaluation.id,
            CallImportEvaluation.progress_counter_gen,
            CallImportEvaluation.progress_flush_seq,
        )
        .filter(CallImportEvaluation.id.in_(ids))
        .all()
    }
    db.rollback()
    for eid, drained in unmatched:
        current = catalog.get(eid)
        if current is None:
            buf.delete(eid)
            continue
        catalog_gen, _catalog_seq = current
        if catalog_gen < drained.gen:
            logger.warning(
                "eval counter gen ahead of catalog for {} (redis {} > catalog {}); recounting",
                eid,
                drained.gen,
                catalog_gen,
            )
            finalize.add(eid)


def sweep_running_evaluations(db: Session, *, now: float | None = None) -> int:
    """Request a fenced recount for running evaluations not recounted lately.

    Selects from the catalog, so it also finds idle evaluations that will
    never be marked dirty again (lost last decrement / lost finalize).
    """
    interval = max(30, int(getattr(settings, "EVAL_PROGRESS_RECOUNT_SECONDS", 300) or 300))
    moment = now if now is not None else time.time()
    rows = (
        db.query(CallImportEvaluation.id)
        .filter(
            or_(
                CallImportEvaluation.status.in_(("running", "cancelled")),
                and_(
                    CallImportEvaluation.status == "auto_aborted",
                    CallImportEvaluation.finished_at.is_(None),
                ),
            )
        )
        .order_by(CallImportEvaluation.updated_at.asc())
        .limit(_SWEEP_LIMIT)
        .all()
    )
    db.rollback()
    requested = 0
    for (eid,) in rows:
        snapshot = buf.read_buffered(eid)
        if snapshot.recount_at is not None and moment - snapshot.recount_at < interval:
            continue
        if buf.request_finalize(eid):
            requested += 1
    if rows:
        # Eval dispatch has no beat of its own; it runs when something asks.
        # A lost request (e.g. one that ran while a bulk-op lock was held)
        # would leave pending rows of a running evaluation idle forever.
        try:
            from app.workers.concurrency.fair_dispatch import schedule_fair_dispatch

            schedule_fair_dispatch(max_workspace_turns=999)
        except Exception as exc:  # noqa: BLE001
            logger.warning("eval dispatch safety-net schedule failed: {}", exc)
    return requested


def _sweep_due() -> bool:
    interval = max(30, int(getattr(settings, "EVAL_PROGRESS_RECOUNT_SECONDS", 300) or 300))
    try:
        return bool(buf._client().set(_SWEEP_GATE_KEY, "1", nx=True, ex=interval))
    except redis.RedisError:
        return False


@celery_app.task(
    name="flush_eval_progress_counters",
    queue=EVAL_CONTROL_QUEUE,
    ignore_result=True,
)
def flush_eval_progress_counters_task() -> dict:
    from app.database import SessionLocal

    try:
        client = buf._client()
        if not client.set(_FLUSHER_LOCK_KEY, "1", nx=True, ex=120):
            return {"skipped": "flusher_running"}
    except redis.RedisError as exc:
        logger.warning("eval progress flush skipped (redis unavailable): {}", exc)
        return {"skipped": "redis_unavailable"}

    db = SessionLocal()
    try:
        stats = flush_eval_progress_counters(db)
        if _sweep_due():
            stats["swept"] = sweep_running_evaluations(db)
        return stats
    finally:
        db.close()
        try:
            buf._client().delete(_FLUSHER_LOCK_KEY)
        except redis.RedisError:
            pass
