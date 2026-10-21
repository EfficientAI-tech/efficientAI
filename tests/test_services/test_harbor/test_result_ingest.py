"""Run summary KPIs, attempt numbering and unfinished-trial handling."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.database import EvaluatorResult
from app.models.enums import EvaluatorResultStatus
from app.services.harbor.result_ingest import (
    assign_attempt_indexes,
    compute_summary,
    fail_unfinished_trials,
    trial_results,
)


def _trial(
    db_session,
    rows,
    *,
    persona_id=None,
    reward,
    passed,
    status=EvaluatorResultStatus.COMPLETED.value,
    minutes=0,
):
    result = EvaluatorResult(
        result_id=str(100000 + db_session.query(EvaluatorResult).count()),
        organization_id=rows.run.organization_id,
        workspace_id=rows.run.workspace_id,
        agent_id=rows.agent.id,
        scenario_id=rows.scenario.id,
        persona_id=persona_id or rows.persona.id,
        simulation_run_id=rows.run.id,
        harbor_trial_name=f"trial-{uuid4().hex[:6]}",
        status=status,
        reward=reward,
        passed=passed,
        speaker_segments=[
            {"speaker": "Speaker 1", "text": "hi"},
            {"speaker": "Speaker 2", "text": "hello"},
        ],
        metric_scores=(
            {str(rows.metric.id): {"value": reward, "type": "rating"}}
            if reward is not None
            else None
        ),
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes),
    )
    db_session.add(result)
    db_session.commit()
    return result


def test_compute_summary_kpis(db_session, sim_rows):
    _trial(db_session, sim_rows, reward=0.9, passed=True, minutes=0)
    _trial(db_session, sim_rows, reward=0.5, passed=False, minutes=1)
    _trial(
        db_session,
        sim_rows,
        reward=None,
        passed=None,
        status=EvaluatorResultStatus.FAILED.value,
        minutes=2,
    )

    summary = compute_summary(db_session, sim_rows.run, trial_results(db_session, sim_rows.run.id))

    assert summary["n_trials"] == 3
    assert summary["n_completed"] == 2
    assert summary["n_failed"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["mean_reward"] == 0.7
    # The only combo has a failed trial, so it isn't "finished" for consistency.
    assert summary["pass_all_rate"] is None
    assert summary["metrics"] == [
        {
            "metric_id": str(sim_rows.metric.id),
            "name": "Empathy",
            "mean": 0.7,
            "n": 2,
            "agent_ids": [],
            "scenario_ids": [],
        }
    ]
    assert summary["golden_mean_reward"] == 0.7
    [combo] = summary["combos"]
    assert combo["attempts"] == 3 and combo["passed"] == 1
    assert combo["scenario_name"] == "Refund for late order"


def test_pass_all_and_pass_any(db_session, sim_rows):
    _trial(db_session, sim_rows, reward=0.9, passed=True, minutes=0)
    _trial(db_session, sim_rows, reward=0.4, passed=False, minutes=1)

    summary = compute_summary(db_session, sim_rows.run, trial_results(db_session, sim_rows.run.id))

    assert summary["pass_all_rate"] == 0.0
    assert summary["pass_any_rate"] == 1.0


def test_attempt_indexes_and_unfinished(db_session, sim_rows):
    later = _trial(
        db_session,
        sim_rows,
        reward=None,
        passed=None,
        status=EvaluatorResultStatus.CALL_IN_PROGRESS.value,
        minutes=5,
    )
    first = _trial(db_session, sim_rows, reward=0.8, passed=True, minutes=0)
    results = trial_results(db_session, sim_rows.run.id)

    assign_attempt_indexes(results)
    fail_unfinished_trials(results, "Trial cancelled")

    assert (first.attempt_index, later.attempt_index) == (1, 2)
    assert later.status == EvaluatorResultStatus.FAILED.value
    assert later.error_message == "Trial cancelled"
    assert first.status == EvaluatorResultStatus.COMPLETED.value
