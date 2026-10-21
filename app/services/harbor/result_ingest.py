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
from app.services.metrics.evaluation_scope import (
    is_fully_golden,
    is_golden_scope,
    load_agent_link_map,
    load_scenario_link_map,
    scope_metric_id,
)

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


def _trial_tool_calls(result: EvaluatorResult) -> list[dict[str, Any]]:
    data = result.call_data if isinstance(result.call_data, dict) else {}
    return [c for c in data.get("tool_calls") or [] if isinstance(c, dict)]


def _tool_expectations_met(result: EvaluatorResult) -> Optional[bool]:
    data = result.call_data if isinstance(result.call_data, dict) else {}
    return (data.get("tool_evaluation") or {}).get("all_expectations_met")


def compute_tool_summary(results: list[EvaluatorResult]) -> Optional[dict[str, Any]]:
    """Run-level tool-use KPIs plus a per-tool breakdown; ``None`` when no tools were used."""
    per_tool: dict[str, dict[str, Any]] = {}
    for r in results:
        for call in _trial_tool_calls(r):
            tool = call.get("tool") or "unknown"
            row = per_tool.setdefault(
                tool,
                {
                    "tool": tool,
                    "provider": call.get("provider"),
                    "calls": 0,
                    "errors": 0,
                    "mocked": 0,
                    "latencies": [],
                    "trials": set(),
                },
            )
            row["calls"] += 1
            row["errors"] += call.get("status") == "error"
            row["mocked"] += call.get("status") == "mocked"
            if call.get("latency_ms") is not None:
                row["latencies"].append(call["latency_ms"])
            row["trials"].add(r.id)
    checked = [m for m in (_tool_expectations_met(r) for r in results) if m is not None]
    if not per_tool and not checked:
        return None
    total = sum(row["calls"] for row in per_tool.values())
    errors = sum(row["errors"] for row in per_tool.values())
    tools = [
        {
            "tool": row["tool"],
            "provider": row["provider"],
            "calls": row["calls"],
            "errors": row["errors"],
            "mocked": row["mocked"],
            "error_rate": round(row["errors"] / row["calls"], 4),
            "avg_latency_ms": round(mean(row["latencies"])) if row["latencies"] else None,
            "trials": len(row["trials"]),
        }
        for row in per_tool.values()
    ]
    tools.sort(key=lambda t: (-t["error_rate"], -t["calls"]))
    return {
        "total_calls": total,
        "errored_calls": errors,
        "success_rate": round((total - errors) / total, 4) if total else None,
        "trials_with_calls": sum(1 for r in results if _trial_tool_calls(r)),
        "expectations_checked": len(checked),
        "expectations_met_rate": (
            round(sum(1 for m in checked if m) / len(checked), 4) if checked else None
        ),
        "tools": tools,
    }


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
    scope_ids = {scope_metric_id(m) for m in metrics}
    agent_link_map = load_agent_link_map(db, scope_ids)
    scenario_link_map = load_scenario_link_map(db, scope_ids)
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
                scope_id = scope_metric_id(metric)
                metric_rows.append(
                    {
                        "metric_id": mid,
                        "name": metric.name,
                        "mean": pass_rate,
                        "pass_rate": pass_rate,
                        "n": len(passes),
                        "agent_ids": (
                            []
                            if is_golden_scope(agent_link_map, scope_id)
                            else [str(a) for a in sorted(agent_link_map.get(scope_id, ()))]
                        ),
                        "scenario_ids": (
                            []
                            if is_golden_scope(scenario_link_map, scope_id)
                            else [str(s) for s in sorted(scenario_link_map.get(scope_id, ()))]
                        ),
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
            scope_id = scope_metric_id(metric)
            metric_rows.append(
                {
                    "metric_id": str(metric.id),
                    "name": metric.name,
                    "mean": round(mean(values), 4),
                    "n": len(values),
                    "agent_ids": (
                        []
                        if is_golden_scope(agent_link_map, scope_id)
                        else [str(a) for a in sorted(agent_link_map.get(scope_id, ()))]
                    ),
                    "scenario_ids": (
                        []
                        if is_golden_scope(scenario_link_map, scope_id)
                        else [str(s) for s in sorted(scenario_link_map.get(scope_id, ()))]
                    ),
                }
            )
    metric_rows.sort(key=lambda m: m["mean"])

    golden_trial_means: list[float] = []
    for r in scored:
        golden_values = [
            v
            for v in (
                normalize_metric_score((r.metric_scores or {}).get(str(metric.id)), metric)
                for metric in metrics
                if is_fully_golden(
                    scope_metric_id(metric),
                    agent_link_map=agent_link_map,
                    scenario_link_map=scenario_link_map,
                )
            )
            if v is not None
        ]
        if golden_values:
            golden_trial_means.append(round(mean(golden_values), 4))

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
                "tool_errors": sum(
                    1 for r in rs for c in _trial_tool_calls(r) if c.get("status") == "error"
                ),
                "tool_expectations_failed": sum(
                    1 for r in rs if _tool_expectations_met(r) is False
                ),
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
        "golden_mean_reward": (
            round(mean(golden_trial_means), 4) if golden_trial_means else None
        ),
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
        "tools": compute_tool_summary(results),
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
