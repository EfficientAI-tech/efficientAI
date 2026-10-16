"""Progress, summary and artifact handling for Harbor simulation runs."""

from __future__ import annotations

import io
import json
import tarfile
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import (
    EvaluatorResult,
    EvaluatorResultStatus,
    Metric,
    Persona,
    Scenario,
    SimulationRun,
)
from app.services.harbor.rewards import normalize_metric_score

LOCAL_ARTIFACT_PREFIX = "local:"
_UNFINISHED_STATUSES = frozenset(
    {
        EvaluatorResultStatus.QUEUED.value,
        EvaluatorResultStatus.CALL_IN_PROGRESS.value,
        EvaluatorResultStatus.EVALUATING.value,
    }
)


def trial_results(db: Session, run_id: UUID) -> list[EvaluatorResult]:
    from app.services.live_entity_storage import hydrate_evaluator_results

    results = (
        db.query(EvaluatorResult)
        .filter(EvaluatorResult.simulation_run_id == run_id)
        .order_by(EvaluatorResult.created_at.asc())
        .all()
    )
    hydrate_evaluator_results(results)
    return results


def refresh_run_progress(db: Session, run: SimulationRun) -> None:
    results = trial_results(db, run.id)
    run.completed_trials = sum(
        1 for r in results if r.status == EvaluatorResultStatus.COMPLETED.value
    )
    run.failed_trials = sum(1 for r in results if r.status == EvaluatorResultStatus.FAILED.value)


def attempt_numbers(results: Iterable[EvaluatorResult]) -> dict[UUID, int]:
    """Number attempts 1..k per scenario × persona in creation order."""
    counters: dict[tuple, int] = defaultdict(int)
    numbers: dict[UUID, int] = {}
    for result in sorted(results, key=lambda r: (r.created_at is None, r.created_at)):
        key = (result.scenario_id, result.persona_id)
        counters[key] += 1
        numbers[result.id] = counters[key]
    return numbers


def assign_attempt_indexes(results: list[EvaluatorResult]) -> None:
    numbers = attempt_numbers(results)
    for result in results:
        result.attempt_index = numbers[result.id]


def fail_unfinished_trials(results: Iterable[EvaluatorResult], reason: str) -> None:
    for result in results:
        if result.status in _UNFINISHED_STATUSES:
            result.status = EvaluatorResultStatus.FAILED.value
            result.error_message = result.error_message or reason


def compute_summary(
    db: Session, run: SimulationRun, results: list[EvaluatorResult]
) -> dict[str, Any]:
    """KPIs for the run page; safe to call while the run is still in progress."""
    scored = [r for r in results if r.reward is not None]
    completed = [r for r in results if r.status == EvaluatorResultStatus.COMPLETED.value]
    failed = [r for r in results if r.status == EvaluatorResultStatus.FAILED.value]

    # Per scenario × persona consistency: pass^k (all attempts pass) and pass@k (any passes).
    combos: dict[tuple, list[EvaluatorResult]] = defaultdict(list)
    for r in results:
        combos[(r.scenario_id, r.persona_id)].append(r)
    finished_combos = [
        rs
        for rs in combos.values()
        if all(r.status == EvaluatorResultStatus.COMPLETED.value for r in rs)
    ]

    metric_ids: set[str] = set()
    for r in scored:
        metric_ids.update((r.metric_scores or {}).keys())
    metrics = (
        db.query(Metric).filter(Metric.id.in_([UUID(m) for m in metric_ids])).all()
        if metric_ids
        else []
    )
    uses_criteria = bool(run.metric_success_criteria)
    criteria_metric_ids = (
        {str(c.get("metric_id")) for c in (run.metric_success_criteria or [])}
        if uses_criteria
        else set()
    )
    metric_rows = []
    for metric in metrics:
        mid = str(metric.id)
        if uses_criteria and mid in criteria_metric_ids:
            passes = []
            for r in scored:
                entry = (r.metric_scores or {}).get(mid)
                if isinstance(entry, dict) and entry.get("passed") is not None:
                    passes.append(bool(entry.get("passed")))
            if passes:
                pass_rate = round(sum(1 for p in passes if p) / len(passes), 4)
                metric_rows.append(
                    {
                        "metric_id": mid,
                        "name": metric.name,
                        "mean": pass_rate,
                        "pass_rate": pass_rate,
                        "n": len(passes),
                    }
                )
            continue
        values = [
            v
            for v in (
                normalize_metric_score((r.metric_scores or {}).get(str(metric.id)), metric)
                for r in scored
            )
            if v is not None
        ]
        if values:
            metric_rows.append(
                {
                    "metric_id": str(metric.id),
                    "name": metric.name,
                    "mean": round(mean(values), 4),
                    "n": len(values),
                }
            )
    metric_rows.sort(key=lambda m: m["mean"])

    scenario_names = (
        {
            s.id: s.name
            for s in db.query(Scenario).filter(Scenario.id.in_([k[0] for k in combos])).all()
        }
        if combos
        else {}
    )
    persona_names = (
        {
            p.id: p.name
            for p in db.query(Persona).filter(Persona.id.in_([k[1] for k in combos])).all()
        }
        if combos
        else {}
    )
    combo_rows = []
    for (scenario_id, persona_id), rs in combos.items():
        rewards = [r.reward for r in rs if r.reward is not None]
        combo_rows.append(
            {
                "scenario_id": str(scenario_id),
                "scenario_name": scenario_names.get(scenario_id),
                "persona_id": str(persona_id),
                "persona_name": persona_names.get(persona_id),
                "attempts": len(rs),
                "passed": sum(1 for r in rs if r.passed),
                "mean_reward": round(mean(rewards), 4) if rewards else None,
            }
        )
    combo_rows.sort(key=lambda c: (c["mean_reward"] is None, c["mean_reward"] or 0))

    turns = [len(r.speaker_segments or []) for r in completed]
    return {
        "n_trials": len(results),
        "n_completed": len(completed),
        "n_failed": len(failed),
        "n_passed": sum(1 for r in scored if r.passed),
        "uses_success_criteria": uses_criteria,
        "pass_rate": round(sum(1 for r in scored if r.passed) / len(scored), 4) if scored else None,
        "mean_reward": round(mean(r.reward for r in scored), 4) if scored else None,
        "pass_all_rate": (
            round(
                sum(1 for rs in finished_combos if all(r.passed for r in rs))
                / len(finished_combos),
                4,
            )
            if finished_combos
            else None
        ),
        "pass_any_rate": (
            round(
                sum(1 for rs in finished_combos if any(r.passed for r in rs))
                / len(finished_combos),
                4,
            )
            if finished_combos
            else None
        ),
        "avg_turns": round(mean(turns), 2) if turns else None,
        "metrics": metric_rows,
        "combos": combo_rows,
    }


def read_harbor_job_stats(job_dir: Path) -> Optional[dict[str, Any]]:
    path = job_dir / "result.json"
    if not path.exists():
        return None
    stats = json.loads(path.read_text()).get("stats") or {}
    return {
        key: stats.get(key)
        for key in (
            "n_completed_trials",
            "n_errored_trials",
            "n_cancelled_trials",
            "n_retries",
            "n_input_tokens",
            "n_output_tokens",
            "cost_usd",
        )
    } | {
        "exception_stats": {
            name: list(ev.get("exception_stats", {}).keys())
            for name, ev in (stats.get("evals") or {}).items()
        }
    }


def archive_run_dir(run: SimulationRun, work_dir: Path) -> Optional[str]:
    """Tar the exported tasks + Harbor job dir; upload to blob storage when enabled."""
    if not work_dir.exists():
        return None
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(work_dir, arcname=f"simulation-run-{run.run_id}")
    data = buf.getvalue()

    from app.services.storage.blob_storage_service import blob_storage_service

    if blob_storage_service.is_enabled():
        key = f"simulation_runs/{run.organization_id}/{run.id}/harbor-{run.run_id}.tar.gz"
        blob_storage_service.upload_file_by_key(data, key, content_type="application/gzip")
        return key
    tarball = work_dir.parent / f"{run.id}.tar.gz"
    tarball.write_bytes(data)
    return f"{LOCAL_ARTIFACT_PREFIX}{tarball}"
