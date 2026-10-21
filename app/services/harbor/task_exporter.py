"""Export simulation run scenarios × personas as Harbor task directories."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import Agent, Metric, Persona, Scenario, SimulationRun
from app.services.metrics.evaluation_scope import (
    applicable_metrics,
    load_agent_link_map,
    load_scenario_link_map,
    scope_metric_id,
)
from app.services.testing.test_agent_simulation_prompt import (
    build_persona_description_for_bridge,
    build_test_agent_system_prompt,
    resolve_persona_max_turns,
)

# Per-trial budgets; the conversation loop is bounded by persona max_turns.
AGENT_TIMEOUT_SEC = 900.0
VERIFIER_TIMEOUT_SEC = 600.0

_TEST_SH = """#!/bin/bash
# Portable grader for running this task outside EfficientAI. EfficientAI runs
# the host-side EfficientAIMetricVerifier instead and never executes this file.
set -euo pipefail
uvx harbor-rewardkit /tests
"""


@dataclass(frozen=True)
class ExportedTask:
    name: str
    path: Path
    scenario_id: UUID
    persona_id: UUID


def run_work_dir(run: SimulationRun) -> Path:
    return Path(settings.HARBOR_WORK_DIR).expanduser().resolve() / str(run.id)


def _slug(text: str, limit: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug[:limit].rstrip("-")) or "x"


def _toml_str(value: object) -> str:
    # JSON string escapes are a subset of TOML basic-string escapes.
    return json.dumps(str(value))


def task_name_for(scenario: Scenario, persona: Persona) -> str:
    # Harbor keeps only the first 32 chars of a task name in trial names.
    return (
        f"{_slug(scenario.name, 11)}-{str(scenario.id)[:6]}"
        f"__{_slug(persona.name, 7)}-{str(persona.id)[:4]}"
    )


def _task_toml(run: SimulationRun, scenario: Scenario, persona: Persona) -> str:
    return "\n".join(
        [
            'schema_version = "1.4"',
            "",
            "[metadata]",
            f"simulation_run_id = {_toml_str(run.id)}",
            f"agent_id = {_toml_str(run.agent_id)}",
            f"scenario_id = {_toml_str(scenario.id)}",
            f"persona_id = {_toml_str(persona.id)}",
            f"scenario_name = {_toml_str(scenario.name)}",
            f"persona_name = {_toml_str(persona.name)}",
            "",
            "[agent]",
            f"timeout_sec = {AGENT_TIMEOUT_SEC}",
            "",
            "[verifier]",
            f"timeout_sec = {VERIFIER_TIMEOUT_SEC}",
            "",
        ]
    )


def _rubric_criterion(metric: Metric) -> list[str] | None:
    metric_type = getattr(metric.metric_type, "value", metric.metric_type)
    description = (metric.description or metric.name or "").strip()
    lines = [
        "[[criterion]]",
        f"id = {_toml_str(metric.id)}",
        f"name = {_toml_str(metric.name)}",
        f"description = {_toml_str(description)}",
    ]
    if metric_type == "boolean":
        lines.append('type = "binary"')
    elif metric_type == "rating":
        lines += ['type = "numeric"', "min = 0", "max = 10"]
    elif metric_type == "number" and isinstance(metric.custom_config, dict):
        lo, hi = metric.custom_config.get("min"), metric.custom_config.get("max")
        if lo is None or hi is None:
            return None
        lines += ['type = "numeric"', f"min = {lo}", f"max = {hi}"]
    else:
        return None
    return lines


def _rubric_toml(metrics: list[Metric]) -> str:
    """RewardKit mirror of the platform metrics so exported tasks stay portable."""
    lines = [
        "[judge]",
        'atif-trajectory = "/logs/agent/trajectory.json"',
        "",
    ]
    for metric in metrics:
        criterion = _rubric_criterion(metric)
        if criterion:
            lines += criterion + [""]
    lines += ["[scoring]", 'aggregation = "weighted-mean"', ""]
    return "\n".join(lines)


def export_tasks(
    db: Session,
    *,
    run: SimulationRun,
    agent: Agent,
    metrics: list[Metric],
) -> list[ExportedTask]:
    """Write one Harbor task per scenario × persona under ``<work_dir>/tasks``.

    Raises ``ValueError`` for missing scenarios/personas: a task that fails to load
    aborts the whole Harbor job, so everything is validated up front.
    """
    scenario_ids = [UUID(str(sid)) for sid in run.scenario_ids or []]
    persona_ids = [UUID(str(pid)) for pid in run.persona_ids or []]
    if not scenario_ids or not persona_ids:
        raise ValueError("Simulation run needs at least one scenario and one persona")

    scenarios = (
        db.query(Scenario)
        .filter(Scenario.id.in_(scenario_ids), Scenario.organization_id == run.organization_id)
        .all()
    )
    personas = (
        db.query(Persona)
        .filter(Persona.id.in_(persona_ids), Persona.organization_id == run.organization_id)
        .all()
    )
    missing = {str(i) for i in scenario_ids} - {str(s.id) for s in scenarios}
    missing |= {str(i) for i in persona_ids} - {str(p.id) for p in personas}
    if missing:
        raise ValueError(f"Scenarios/personas not found: {', '.join(sorted(missing))}")

    tasks_root = run_work_dir(run) / "tasks"
    shutil.rmtree(tasks_root, ignore_errors=True)
    scope_ids = {scope_metric_id(m) for m in metrics}
    agent_link_map = load_agent_link_map(db, scope_ids)
    scenario_link_map = load_scenario_link_map(db, scope_ids)
    run_agent_id = UUID(str(run.agent_id)) if run.agent_id else None

    exported: list[ExportedTask] = []
    for scenario in sorted(scenarios, key=lambda s: str(s.name)):
        scenario_metrics = applicable_metrics(
            metrics,
            agent_id=run_agent_id,
            scenario_id=scenario.id,
            agent_link_map=agent_link_map,
            scenario_link_map=scenario_link_map,
        )
        rubric = _rubric_toml(scenario_metrics)
        for persona in sorted(personas, key=lambda p: str(p.name)):
            name = task_name_for(scenario, persona)
            if (tasks_root / name).exists():  # id-prefix collision; keep names unique
                name = f"{name[:26]}-{len(exported):05d}"
            task_dir = tasks_root / name
            (task_dir / "environment").mkdir(parents=True, exist_ok=True)
            (task_dir / "tests").mkdir(parents=True, exist_ok=True)
            (task_dir / "instruction.md").write_text(
                build_test_agent_system_prompt(
                    agent,
                    persona,
                    scenario,
                    persona_description=build_persona_description_for_bridge(persona),
                    max_turns=resolve_persona_max_turns(persona),
                )
            )
            (task_dir / "task.toml").write_text(_task_toml(run, scenario, persona))
            test_sh = task_dir / "tests" / "test.sh"
            test_sh.write_text(_TEST_SH)
            test_sh.chmod(0o755)
            (task_dir / "tests" / "rubric.toml").write_text(rubric)
            exported.append(
                ExportedTask(
                    name=name, path=task_dir, scenario_id=scenario.id, persona_id=persona.id
                )
            )
    return exported
