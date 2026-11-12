"""Redis-buffered evaluation progress counters.

Runs the Lua scripts against a real Redis (``EVAL_BUFFER_TEST_REDIS_URL``,
default ``redis://localhost:6379/15``) and skips when none is reachable.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import redis

from app.models.database import CallImportEvaluation
from app.services.call_imports import eval_progress_buffer as buf
from app.workers.tasks import flush_eval_progress as flusher
from app.workers.tasks.evaluate_call_import_row_core import (
    commit_terminal_row_and_rollup,
    finalize_evaluation_progress,
    recount_evaluation_counters,
    record_buffered_transition,
)
from tests.test_workers.test_evaluate_call_import_row import _seed

_TEST_REDIS_URL = os.getenv("EVAL_BUFFER_TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture
def rclient(monkeypatch):
    client = redis.from_url(_TEST_REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.RedisError:
        pytest.skip(f"redis not reachable at {_TEST_REDIS_URL}")
    client.flushdb()
    monkeypatch.setattr(buf, "_redis", client)
    monkeypatch.setattr(buf, "_scripts", {})
    monkeypatch.setattr(
        "app.workers.concurrency.limits.read_job_inflight", lambda _eid: 0
    )
    yield client
    client.flushdb()


@pytest.fixture
def finalize_calls(monkeypatch):
    calls: list[str] = []

    def _request(eid):
        calls.append(str(eid))
        return True

    monkeypatch.setattr(buf, "request_finalize", _request)
    return calls


def _running_eval(db_session, *, row_count: int, statuses: list[str] | None = None):
    _, _, _, _, evaluation, eval_rows = _seed(db_session, row_count=row_count)
    evaluation.total_rows = row_count
    evaluation.status = "running"
    evaluation.started_at = datetime.now(timezone.utc)
    for row, status in zip(eval_rows, statuses or ["running"] * row_count):
        row.status = status
    db_session.commit()
    return evaluation, eval_rows


def _complete(db_session, evaluation, eval_row, status="completed"):
    """Shard transition + buffered record, like the worker hot path."""
    eval_row.status = status
    eval_row.finished_at = datetime.now(timezone.utc)
    commit_terminal_row_and_rollup(
        db_session, evaluation, eval_row, previous_row_status="running"
    )


def _catalog(db_session, evaluation):
    db_session.expire_all()
    row = db_session.get(CallImportEvaluation, evaluation.id)
    return row.completed_rows, row.failed_rows


# --- pure helpers -------------------------------------------------------------


def test_remaining_delta_for_transition():
    assert buf.remaining_delta_for_transition("running", "completed") == -1
    assert buf.remaining_delta_for_transition("pending", "failed") == -1
    assert buf.remaining_delta_for_transition("failed", "pending") == 1
    assert buf.remaining_delta_for_transition("completed", "failed") == 0


def test_unapplied_deltas_counts_pending_only_until_applied():
    snap = buf.BufferedCounters(
        completed_delta=2,
        failed_delta=1,
        pending_completed=5,
        pending_failed=0,
        pending_gen=3,
        pending_seq=7,
        gen=3,
    )
    assert buf.unapplied_deltas(snap, catalog_gen=3, catalog_seq=6) == (7, 1)
    # Catalog already applied seq 7 (ambiguous commit): don't double it.
    assert buf.unapplied_deltas(snap, catalog_gen=3, catalog_seq=7) == (2, 1)
    # A recount moved the catalog to gen 4: Redis view is stale.
    assert buf.unapplied_deltas(snap, catalog_gen=4, catalog_seq=6) == (0, 0)


# --- Lua scripts -----------------------------------------------------------------


def test_record_drain_ack_cycle(rclient):
    eid = "00000000-0000-0000-0000-000000000001"
    buf.seed(eid, gen=2, seq=10, remaining=3)
    res = buf.record_transition(eid, completed_delta=1, failed_delta=0, remaining_delta=-1)
    assert (res.remaining, res.created) == (2, False)
    assert rclient.sismember(buf.DIRTY_SET_KEY, eid)

    drained = buf.drain(eid)
    assert (drained.kind, drained.completed_delta, drained.gen, drained.seq) == (
        "pending",
        1,
        2,
        11,
    )
    # Not acked yet: a second drain re-sends the identical slot.
    again = buf.drain(eid)
    assert (again.seq, again.completed_delta) == (11, 1)

    buf.ack(eid, 11)
    assert not rclient.sismember(buf.DIRTY_SET_KEY, eid)
    assert buf.drain(eid).kind == "empty"


def test_new_deltas_while_slot_pending_stay_buffered(rclient):
    eid = "00000000-0000-0000-0000-000000000002"
    buf.seed(eid, gen=0, seq=0, remaining=5)
    buf.record_transition(eid, completed_delta=1, failed_delta=0, remaining_delta=-1)
    first = buf.drain(eid)
    buf.record_transition(eid, completed_delta=0, failed_delta=1, remaining_delta=-1)
    buf.ack(eid, first.seq)
    assert rclient.sismember(buf.DIRTY_SET_KEY, eid)  # f=1 still unflushed
    second = buf.drain(eid)
    assert (second.completed_delta, second.failed_delta, second.seq) == (0, 1, first.seq + 1)


def test_missing_key_is_marked_uninit(rclient):
    eid = "00000000-0000-0000-0000-000000000003"
    res = buf.record_transition(eid, completed_delta=1, failed_delta=0, remaining_delta=-1)
    assert res.created is True
    assert buf.drain(eid).kind == "uninit"


def test_fence_discards_and_parks_remaining(rclient):
    eid = "00000000-0000-0000-0000-000000000004"
    buf.seed(eid, gen=1, seq=4, remaining=10)
    buf.record_transition(eid, completed_delta=3, failed_delta=0, remaining_delta=-3)
    buf.drain(eid)  # pending slot seq 5
    buf.record_transition(eid, completed_delta=1, failed_delta=0, remaining_delta=-1)

    buf.fence(eid, gen=2, catalog_seq=3)
    snap = buf.read_buffered(eid)
    assert (snap.completed_delta, snap.pending_seq, snap.gen) == (0, None, 2)
    # Row finishing between fence and count must not look like "done".
    res = buf.record_transition(eid, completed_delta=1, failed_delta=0, remaining_delta=-1)
    assert res.remaining > 0
    # Shard count says 4 still in flight; the post-fence decrement is kept.
    assert buf.set_remaining_after_count(eid, gen=2, in_progress=4) == 3
    # seq never goes backwards (catalog_seq 3 < redis seq 5).
    assert int(rclient.hget(buf.counter_key(eid), "seq")) == 5
    # A stale recount cannot overwrite remaining.
    assert buf.set_remaining_after_count(eid, gen=1, in_progress=99) is None


# --- flush against the catalog ------------------------------------------------------


def test_flush_applies_once_and_is_idempotent(db_session, rclient, finalize_calls):
    evaluation, rows = _running_eval(db_session, row_count=3)
    buf.seed(evaluation.id, gen=0, seq=0, remaining=3)
    _complete(db_session, evaluation, rows[0])
    _complete(db_session, evaluation, rows[1], status="failed")
    assert _catalog(db_session, evaluation) == (0, 0)  # no per-row catalog write

    drained = buf.drain(evaluation.id)
    batch = [(evaluation.id, drained)]
    assert flusher.apply_flush_batch(db_session, batch) == {evaluation.id}
    db_session.commit()
    # Same payload again (e.g. ack lost): seq guard makes it a no-op.
    assert flusher.apply_flush_batch(db_session, batch) == set()
    db_session.commit()
    assert _catalog(db_session, evaluation) == (1, 1)


def test_ambiguous_commit_is_not_double_applied(db_session, rclient, finalize_calls, monkeypatch):
    evaluation, rows = _running_eval(db_session, row_count=2)
    buf.seed(evaluation.id, gen=0, seq=0, remaining=2)
    _complete(db_session, evaluation, rows[0])

    # Commit lands, but the ack never happens (client saw an error).
    monkeypatch.setattr(buf, "ack", MagicMock(side_effect=redis.ConnectionError("boom")))
    flusher.flush_eval_progress_counters(db_session)
    assert _catalog(db_session, evaluation) == (1, 0)
    monkeypatch.undo()
    monkeypatch.setattr(buf, "_redis", rclient)
    monkeypatch.setattr(buf, "request_finalize", lambda _eid: True)

    stats = flusher.flush_eval_progress_counters(db_session)
    assert stats["stale"] == 1
    assert _catalog(db_session, evaluation) == (1, 0)
    assert not rclient.sismember(buf.DIRTY_SET_KEY, str(evaluation.id))


def test_failed_catalog_write_keeps_slot_for_resend(db_session, rclient, finalize_calls, monkeypatch):
    evaluation, rows = _running_eval(db_session, row_count=2)
    buf.seed(evaluation.id, gen=0, seq=0, remaining=2)
    _complete(db_session, evaluation, rows[0])

    monkeypatch.setattr(
        flusher, "apply_flush_batch", MagicMock(side_effect=RuntimeError("db down"))
    )
    assert flusher.flush_eval_progress_counters(db_session)["failed"] is True
    snap = buf.read_buffered(evaluation.id)
    assert (snap.pending_completed, snap.pending_seq) == (1, 1)

    monkeypatch.undo()
    monkeypatch.setattr(buf, "_redis", rclient)
    monkeypatch.setattr(buf, "request_finalize", lambda _eid: True)
    flusher.flush_eval_progress_counters(db_session)
    assert _catalog(db_session, evaluation) == (1, 0)
    assert buf.read_buffered(evaluation.id).pending_seq is None


def test_recount_supersedes_inflight_flush(db_session, rclient, finalize_calls):
    evaluation, rows = _running_eval(db_session, row_count=3)
    buf.seed(evaluation.id, gen=0, seq=0, remaining=3)
    _complete(db_session, evaluation, rows[0])
    _complete(db_session, evaluation, rows[1])
    drained = buf.drain(evaluation.id)  # gen 0, +2

    in_progress = recount_evaluation_counters(db_session, evaluation)
    db_session.commit()
    assert in_progress == 1
    assert _catalog(db_session, evaluation) == (2, 0)

    # The flush drained before the fence now matches nothing.
    assert flusher.apply_flush_batch(db_session, [(evaluation.id, drained)]) == set()
    db_session.commit()
    assert _catalog(db_session, evaluation) == (2, 0)
    assert int(rclient.hget(buf.counter_key(evaluation.id), "remaining")) == 1


def test_older_recount_cannot_overwrite_newer(db_session, rclient, monkeypatch):
    evaluation, _rows = _running_eval(db_session, row_count=2, statuses=["completed", "completed"])
    from app.workers.tasks import evaluate_call_import_row_core as core

    real_count = core._count_evaluation_rows

    def _count_then_newer_recount(db, eid):
        real_count(db, eid)
        # Another recount bumps the gen while this one is still counting.
        db.execute(
            CallImportEvaluation.__table__.update()
            .where(CallImportEvaluation.id == eid)
            .values(progress_counter_gen=CallImportEvaluation.progress_counter_gen + 1)
        )
        return (9, 9, 0, 0)  # what a stale count would write

    monkeypatch.setattr(core, "_count_evaluation_rows", _count_then_newer_recount)
    recount_evaluation_counters(db_session, evaluation)
    db_session.commit()
    db_session.expire_all()
    row = db_session.get(CallImportEvaluation, evaluation.id)
    assert (row.total_rows, row.completed_rows) == (2, 0)


# --- safety nets ------------------------------------------------------------------


def test_last_row_requests_finalize(db_session, rclient, finalize_calls):
    evaluation, rows = _running_eval(db_session, row_count=2)
    buf.seed(evaluation.id, gen=0, seq=0, remaining=2)
    _complete(db_session, evaluation, rows[0])
    assert finalize_calls == []
    _complete(db_session, evaluation, rows[1])
    assert finalize_calls == [str(evaluation.id)]


def test_lost_redis_key_requests_recount(db_session, rclient, finalize_calls):
    evaluation, rows = _running_eval(db_session, row_count=3)
    buf.seed(evaluation.id, gen=0, seq=0, remaining=3)
    rclient.delete(buf.counter_key(evaluation.id))  # eviction / restart
    _complete(db_session, evaluation, rows[0])
    assert finalize_calls == [str(evaluation.id)]
    # Flusher never flushes an uninit hash.
    assert flusher.flush_eval_progress_counters(db_session)["drained"] == 0


def test_redis_down_falls_back_to_direct_write(db_session, rclient, monkeypatch):
    evaluation, rows = _running_eval(db_session, row_count=2)
    monkeypatch.setattr(
        buf, "record_transition", MagicMock(side_effect=redis.ConnectionError("down"))
    )
    assert record_buffered_transition(
        evaluation.id, previous_row_status="running", new_row_status="completed"
    ) is False
    _complete(db_session, evaluation, rows[0])
    assert _catalog(db_session, evaluation) == (1, 0)


def test_sweep_finds_idle_running_evaluations(db_session, rclient, finalize_calls):
    evaluation, _rows = _running_eval(db_session, row_count=1)
    # Never recounted and not dirty: only the catalog sweep can find it.
    assert flusher.sweep_running_evaluations(db_session) >= 1
    assert str(evaluation.id) in finalize_calls

    finalize_calls.clear()
    buf.fence(evaluation.id, gen=1, catalog_seq=0)  # stamps recount_at = now
    flusher.sweep_running_evaluations(db_session)
    assert str(evaluation.id) not in finalize_calls


def test_finalize_closes_run_from_shard_counts(db_session, rclient, finalize_calls, monkeypatch):
    monkeypatch.setattr(
        "app.services.call_imports.eval_flexprice_billing.maybe_finalize_evaluation_flexprice_billing",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.services.call_imports.metric_aggregate_cache.maybe_refresh_aggregate_cache_after_row",
        lambda *_a, **_k: None,
    )
    evaluation, rows = _running_eval(db_session, row_count=3)
    buf.seed(evaluation.id, gen=0, seq=0, remaining=3)
    _complete(db_session, evaluation, rows[0])
    flusher.flush_eval_progress_counters(db_session)
    _complete(db_session, evaluation, rows[1])
    _complete(db_session, evaluation, rows[2], status="failed")

    assert finalize_evaluation_progress(db_session, evaluation.id) == "partial"
    db_session.expire_all()
    row = db_session.get(CallImportEvaluation, evaluation.id)
    assert (row.completed_rows, row.failed_rows, row.status) == (2, 1, "partial")
    assert row.finished_at is not None
    assert not rclient.exists(buf.counter_key(evaluation.id))


def test_finalize_waits_while_rows_in_flight(db_session, rclient, finalize_calls):
    evaluation, rows = _running_eval(db_session, row_count=2)
    buf.seed(evaluation.id, gen=0, seq=0, remaining=2)
    _complete(db_session, evaluation, rows[0])
    assert finalize_evaluation_progress(db_session, evaluation.id) == "in_progress"
    db_session.expire_all()
    row = db_session.get(CallImportEvaluation, evaluation.id)
    assert (row.status, row.completed_rows) == ("running", 1)
    assert int(rclient.hget(buf.counter_key(evaluation.id), "remaining")) == 1


def test_ui_merge_includes_unflushed_deltas(db_session, rclient, finalize_calls):
    from app.services.call_imports.progress_counters import merge_eval_counters_for_ui

    evaluation, rows = _running_eval(db_session, row_count=3)
    buf.seed(evaluation.id, gen=0, seq=0, remaining=3)
    _complete(db_session, evaluation, rows[0])
    _complete(db_session, evaluation, rows[1])
    db_session.expire_all()
    row = db_session.get(CallImportEvaluation, evaluation.id)
    assert merge_eval_counters_for_ui(row) == (2, 0)

    flusher.flush_eval_progress_counters(db_session)
    db_session.expire_all()
    row = db_session.get(CallImportEvaluation, evaluation.id)
    assert (row.completed_rows, merge_eval_counters_for_ui(row)) == (2, (2, 0))
