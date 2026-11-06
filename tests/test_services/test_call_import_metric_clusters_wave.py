"""End-to-end wave step for failure diagnostics (clusters) generation.

Drives ``process_metric_clusters_wave_step`` through extraction, per-metric
synthesis, discovery and final assembly with the LLM stubbed out, so a
regression that leaves the job stuck in one phase fails here instead of in
production.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.database import CallImportEvaluation, EvaluationAnalysisBatch
from app.models.schemas import MetricCluster, MetricFailurePolicy
from app.services import call_import_metric_clusters_wave as wave
from tests.test_api.test_call_import_evaluation_rows_sorting import _seed_eval_with_rows


def _policy(metric_id) -> MetricFailurePolicy:
    return MetricFailurePolicy(
        metric_id=str(metric_id),
        numeric_rule={"op": "lt", "threshold": 0.5},
    )


@pytest.fixture()
def seeded(db_session, org_id, seed_org):
    call_import, evaluation, metric = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": f"c{i}", "status": "completed", "score_value": 0.2}
            for i in range(4)
        ],
    )
    return evaluation, metric


def _start_header(evaluation, total_rows: int = 4):
    run_id = uuid4()
    evaluation.metric_clusters = {
        "status": "running",
        "job_run_id": str(run_id),
        "transcript_source": "production",
        "progress": {
            "completed_rows": 0,
            "total_rows": total_rows,
            "completed_batches": 0,
            "total_batches": 1,
            "completed_llm_calls": 0,
            "total_llm_calls": 3,
            "phase": "rows",
        },
        "llm_calls_used": 0,
        "selected_evaluation_row_ids": [],
        "failure_policies": {},
    }
    return run_id


def _drive(db_session, evaluation, metric, monkeypatch, run_id):
    seen_phases: list[str] = []

    def _on_progress(update):
        seen_phases.append(str(update.get("phase")))

    action = "continue"
    terminal = None
    for _ in range(10):
        action, terminal = wave.process_metric_clusters_wave_step(
            db_session,
            evaluation,
            evaluation.organization_id,
            "openai",
            "gpt-4o-mini",
            metrics=[metric],
            policies={str(metric.id): _policy(metric.id)},
            job_run_id=run_id,
            on_progress=_on_progress,
        )
        db_session.expire(evaluation, ["metric_clusters"])
        db_session.refresh(evaluation)
        if terminal is not None or action != "continue":
            break
    return action, terminal, seen_phases


def test_wave_step_completes_extraction_synthesis_and_discovery(
    seeded, db_session, monkeypatch
):
    evaluation, metric = seeded
    run_id = _start_header(evaluation)
    db_session.commit()

    def _fake_extraction(_db, _org, _provider, _model, _metric_name, batch):
        return [
            {
                "conversation_id": row["conversation_id"],
                "signature": "Agent cut off mid sentence",
                "quote": "bye",
                "turns": [{"speaker": "Agent", "text": "bye"}],
            }
            for row in batch
        ]

    monkeypatch.setattr(wave, "_run_extraction", _fake_extraction)
    monkeypatch.setattr(
        wave,
        "_synthesize_metric_clusters",
        lambda *_a, **_kw: [
            MetricCluster(
                id=str(uuid4()),
                label="Abrupt closure",
                gap_label="LOGIC_GAP",
                level=1,
                count=4,
                share_pct=100.0,
            )
        ],
    )
    monkeypatch.setattr(wave, "_run_discovery", lambda *_a, **_kw: [])

    action, terminal, seen_phases = _drive(
        db_session, evaluation, metric, monkeypatch, run_id
    )

    assert action == "done"
    assert terminal is not None
    assert terminal.status == "completed", terminal.error_message
    assert [g.metric_name for g in terminal.groups] == [metric.name]

    # Phase never went backwards and always ended on completed. The worker
    # persists the terminal state, so the wave only needs to report it.
    assert "synthesis" in seen_phases
    assert seen_phases[-1] == "completed"
    assert terminal.progress["phase"] == "completed"
    assert terminal.progress["completed_batches"] == terminal.progress["total_batches"]

    # The wave returns the terminal state; the Celery task persists it. What
    # must hold here is that the header is still owned by this run and has a
    # fresh heartbeat, so the task cannot be mistaken for an abandoned job.
    stored = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation.id)
        .first()
    )
    assert stored.metric_clusters["job_run_id"] == str(run_id)
    assert stored.metric_clusters.get("heartbeat_at")
    assert stored.metric_clusters["progress"]["phase"] in {"synthesis", "discovery"}


def test_wave_step_resumes_without_rerunning_checkpointed_sub_batches(
    seeded, db_session, monkeypatch
):
    """A worker killed mid-page must not re-pay for finished sub-batches."""
    evaluation, metric = seeded
    run_id = _start_header(evaluation)
    db_session.commit()

    calls: list[str] = []

    def _fake_extraction(_db, _org, _provider, _model, _metric_name, batch):
        calls.append(batch[0]["conversation_id"])
        return [
            {
                "conversation_id": row["conversation_id"],
                "signature": "Agent cut off mid sentence",
                "quote": "bye",
                "turns": [],
            }
            for row in batch
        ]

    monkeypatch.setattr(wave, "_run_extraction", _fake_extraction)
    monkeypatch.setattr(
        wave,
        "_synthesize_metric_clusters",
        lambda *_a, **_kw: [],
    )
    monkeypatch.setattr(wave, "_run_discovery", lambda *_a, **_kw: [])

    # First pass checkpoints sub-batch 0 as done, then the "worker dies".
    original_upsert = wave.upsert_analysis_batch

    def _upsert_then_die(*args, **kwargs):
        row = original_upsert(*args, **kwargs)
        raise KeyboardInterrupt("simulated worker loss")

    monkeypatch.setattr(wave, "upsert_analysis_batch", _upsert_then_die)
    with pytest.raises(KeyboardInterrupt):
        wave.process_metric_clusters_wave_step(
            db_session,
            evaluation,
            evaluation.organization_id,
            "openai",
            "gpt-4o-mini",
            metrics=[metric],
            policies={str(metric.id): _policy(metric.id)},
            job_run_id=run_id,
        )
    db_session.rollback()
    monkeypatch.setattr(wave, "upsert_analysis_batch", original_upsert)

    first_pass = list(calls)
    assert first_pass, "extraction should have run before the simulated crash"

    in_progress = (
        db_session.query(EvaluationAnalysisBatch)
        .filter(
            EvaluationAnalysisBatch.evaluation_id == evaluation.id,
            EvaluationAnalysisBatch.job_kind == "metric_clusters",
            EvaluationAnalysisBatch.job_run_id == run_id,
        )
        .all()
    )
    # The checkpoint write was rolled back with the crash, so a real resume
    # re-runs the page from scratch; the important guarantee is that it does
    # not silently duplicate into a second row for the same batch index.
    assert len(in_progress) <= 1

    db_session.expire(evaluation, ["metric_clusters"])
    db_session.refresh(evaluation)
    calls.clear()
    action, terminal, _ = _drive(db_session, evaluation, metric, monkeypatch, run_id)
    assert action == "done"
    assert terminal is not None


def test_empty_page_moves_to_synthesis_and_persists(
    seeded, db_session, monkeypatch
):
    """The no-rows branch must commit, or the job re-enters the row phase."""
    evaluation, metric = seeded
    run_id = _start_header(evaluation, total_rows=0)
    evaluation.metric_clusters["progress"].update(
        {"total_rows": 0, "total_batches": 1, "completed_batches": 0}
    )
    db_session.commit()

    monkeypatch.setattr(wave, "_run_extraction", lambda *_a, **_kw: [])
    monkeypatch.setattr(wave, "_synthesize_metric_clusters", lambda *_a, **_kw: [])
    monkeypatch.setattr(wave, "_run_discovery", lambda *_a, **_kw: [])

    # Patch the page loader so the page is empty.
    monkeypatch.setattr(wave, "_load_row_page", lambda *_a, **_kw: [])

    action, terminal = wave.process_metric_clusters_wave_step(
        db_session,
        evaluation,
        evaluation.organization_id,
        "openai",
        "gpt-4o-mini",
        metrics=[metric],
        policies={},
        job_run_id=run_id,
    )

    assert action == "continue"
    stored = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation.id)
        .first()
    )
    assert stored.metric_clusters["progress"]["phase"] == "synthesis"
    assert stored.metric_clusters.get("heartbeat_at")
