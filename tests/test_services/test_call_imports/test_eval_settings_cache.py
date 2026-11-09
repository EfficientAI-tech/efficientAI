"""Per-row catalog reads on the eval worker path: settings snapshot cache,
Redis settings version, guarded status flip, cached import context."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
import redis
from sqlalchemy import event

from app.models.database import CallImportEvaluation
from app.services.call_imports import eval_progress_buffer as buf
from app.services.call_imports import eval_settings_version as ver
from app.workers.catalog_cache import clear_worker_catalog_cache
from app.workers.tasks.evaluate_call_import_row_core import (
    EvaluationSnapshot,
    commit_terminal_row_and_rollup,
    load_call_import_eval_context,
    load_evaluation_snapshot,
    mark_evaluation_running_if_pending,
)
from tests.test_workers.test_evaluate_call_import_row import (
    _patch_dependencies,
    _seed,
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_worker_catalog_cache()
    yield
    clear_worker_catalog_cache()


@pytest.fixture
def redis_ok():
    try:
        buf._client().ping()
    except redis.RedisError:
        pytest.skip("redis not reachable for eval settings version tests")


@contextmanager
def count_statements(db_session, *tables: str):
    """Count SQL statements that mention any of ``tables``."""
    seen: list[str] = []
    bind = db_session.get_bind()
    engine = getattr(bind, "engine", bind)

    def _before(_conn, _cursor, statement, _params, _context, _many):
        lowered = statement.lower()
        if any(t in lowered for t in tables):
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def _evaluation(db_session, status="running"):
    _, call_import, _metrics, _source_rows, evaluation, eval_rows = _seed(
        db_session, row_count=2
    )
    evaluation.status = status
    evaluation.total_rows = 2
    db_session.commit()
    return call_import, evaluation, eval_rows


# --- settings version hook ------------------------------------------------------


def test_hook_bumps_on_watched_change_and_delete(db_session, redis_ok):
    _ci, evaluation, _rows = _evaluation(db_session)
    start = ver.read_settings_version(evaluation.id)

    evaluation.llm_model = "gpt-new"
    db_session.commit()
    assert ver.read_settings_version(evaluation.id) == start + 1

    evaluation.discovered_metric_aliases = {"a": "b"}
    db_session.commit()
    assert ver.read_settings_version(evaluation.id) == start + 2


def test_hook_ignores_counters_and_rollback(db_session, redis_ok):
    _ci, evaluation, _rows = _evaluation(db_session)
    start = ver.read_settings_version(evaluation.id)

    evaluation.completed_rows = 1
    evaluation.failed_rows = 1
    db_session.commit()
    assert ver.read_settings_version(evaluation.id) == start

    evaluation.llm_model = "never-committed"
    db_session.flush()
    db_session.rollback()
    assert ver.read_settings_version(evaluation.id) == start


def test_hook_bumps_on_delete(db_session, redis_ok):
    _ci, evaluation, _rows = _evaluation(db_session)
    eid = evaluation.id
    start = ver.read_settings_version(eid)
    db_session.delete(evaluation)
    db_session.commit()
    assert ver.read_settings_version(eid) == start + 1


# --- snapshot cache -----------------------------------------------------------------


def test_snapshot_cache_hits_until_version_bump(db_session, redis_ok):
    _ci, evaluation, _rows = _evaluation(db_session)
    eid, model = evaluation.id, evaluation.llm_model
    with count_statements(db_session, "from call_import_evaluations") as seen:
        first = load_evaluation_snapshot(db_session, eid)
        for _ in range(5):
            load_evaluation_snapshot(db_session, eid)
    assert isinstance(first, EvaluationSnapshot)
    assert first.llm_model == model
    assert len(seen) == 1

    evaluation.llm_model = "gpt-retry"
    db_session.commit()
    with count_statements(db_session, "from call_import_evaluations") as seen:
        fresh = load_evaluation_snapshot(db_session, eid)
    assert fresh.llm_model == "gpt-retry"
    assert len(seen) == 1


def test_snapshot_reads_catalog_when_redis_down(db_session, monkeypatch):
    _ci, evaluation, _rows = _evaluation(db_session)
    eid = evaluation.id
    monkeypatch.setattr(ver, "read_settings_version", lambda _eid: None)
    with count_statements(db_session, "from call_import_evaluations") as seen:
        load_evaluation_snapshot(db_session, eid)
        load_evaluation_snapshot(db_session, eid)
    assert len(seen) == 2


def test_snapshot_copies_are_independent(db_session, redis_ok):
    _ci, evaluation, _rows = _evaluation(db_session)
    evaluation.llm_config = {"temperature": 0.1}
    db_session.commit()
    one = load_evaluation_snapshot(db_session, evaluation.id)
    one.llm_config["temperature"] = 9
    one.status = "mutated"
    two = load_evaluation_snapshot(db_session, evaluation.id)
    assert two.llm_config == {"temperature": 0.1}
    assert two.status == "running"


def test_missing_evaluation_returns_none(db_session, redis_ok):
    import uuid

    assert load_evaluation_snapshot(db_session, uuid.uuid4()) is None


# --- guarded pending -> running flip ------------------------------------------------------


def test_flip_runs_once_and_bumps_version(db_session, redis_ok):
    _ci, evaluation, _rows = _evaluation(db_session, status="pending")
    start = ver.read_settings_version(evaluation.id)
    snap = load_evaluation_snapshot(db_session, evaluation.id)
    mark_evaluation_running_if_pending(db_session, snap)
    assert snap.status == "running"
    db_session.expire_all()
    row = db_session.get(CallImportEvaluation, evaluation.id)
    assert row.status == "running"
    assert row.started_at is not None
    assert ver.read_settings_version(evaluation.id) == start + 1

    # Already running: no SQL at all.
    with count_statements(db_session, "call_import_evaluations") as seen:
        mark_evaluation_running_if_pending(db_session, snap)
    assert seen == []


def test_flip_does_not_overwrite_other_status(db_session, redis_ok):
    _ci, evaluation, _rows = _evaluation(db_session, status="pending")
    snap = load_evaluation_snapshot(db_session, evaluation.id)  # cached "pending"
    evaluation.status = "cancelled"
    db_session.commit()
    mark_evaluation_running_if_pending(db_session, snap)
    db_session.expire_all()
    assert db_session.get(CallImportEvaluation, evaluation.id).status == "cancelled"


# --- Redis-down rollup reloads an attached object ----------------------------------------


def test_redis_down_rollup_reloads_orm_object(db_session, monkeypatch):
    from datetime import datetime, timezone

    _ci, evaluation, rows = _evaluation(db_session)
    rows[0].status = "running"
    db_session.commit()
    monkeypatch.setattr(
        "app.workers.tasks.evaluate_call_import_row_core.record_buffered_transition",
        lambda *_a, **_k: False,
    )
    snap = load_evaluation_snapshot(db_session, evaluation.id)
    rows[0].status = "completed"
    rows[0].finished_at = datetime.now(timezone.utc)
    commit_terminal_row_and_rollup(
        db_session, snap, rows[0], previous_row_status="running"
    )
    db_session.expire_all()
    assert db_session.get(CallImportEvaluation, evaluation.id).completed_rows == 1


# --- import context -------------------------------------------------------------------


def test_import_context_cached_and_copied(db_session):
    call_import, _evaluation_row, _rows = _evaluation(db_session)
    call_import.custom_column_mapping = {"Agent": "agent"}
    db_session.commit()
    cid = call_import.id
    with count_statements(db_session, "from call_imports") as seen:
        mapping, _aliases = load_call_import_eval_context(db_session, cid)
        mapping["Agent"] = "mutated"
        again, _ = load_call_import_eval_context(db_session, cid)
    assert again == {"Agent": "agent"}
    assert len(seen) == 1
    assert "cast" not in seen[0].lower()


def test_import_context_missing_import(db_session):
    import uuid

    assert load_call_import_eval_context(db_session, uuid.uuid4()) == ({}, None)
    assert load_call_import_eval_context(db_session, None) == ({}, None)


# --- end to end: second row makes no catalog reads -------------------------------------


def test_second_row_issues_no_catalog_statements(db_session, monkeypatch, redis_ok):
    _ci, evaluation, eval_rows = _evaluation(db_session)
    task_module = _patch_dependencies(monkeypatch, db_session)

    first = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))
    assert first["status"] == "completed"

    with count_statements(
        db_session, "from call_import_evaluations ", "from call_imports ",
        "update call_import_evaluations",
    ) as seen:
        second = task_module.evaluate_call_import_row_task.run(str(eval_rows[1].id))
    assert second["status"] == "completed"
    assert seen == [], seen
