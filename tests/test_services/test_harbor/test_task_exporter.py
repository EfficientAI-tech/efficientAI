"""Exported Harbor task directories."""

import tomllib

import pytest

from app.services.harbor.task_exporter import export_tasks, run_work_dir


def test_export_tasks_writes_one_task_per_scenario_persona(db_session, sim_rows, harbor_work_dir):
    tasks = export_tasks(
        db_session, run=sim_rows.run, agent=sim_rows.agent, metrics=[sim_rows.metric]
    )

    assert len(tasks) == 1
    task = tasks[0]
    assert task.path.parent == run_work_dir(sim_rows.run) / "tasks"
    assert {p.name for p in task.path.iterdir()} == {
        "environment",
        "tests",
        "instruction.md",
        "task.toml",
    }
    assert (task.path / "tests" / "test.sh").stat().st_mode & 0o111

    config = tomllib.loads((task.path / "task.toml").read_text())
    assert config["metadata"]["scenario_id"] == str(sim_rows.scenario.id)
    assert config["metadata"]["persona_id"] == str(sim_rows.persona.id)
    assert config["metadata"]["simulation_run_id"] == str(sim_rows.run.id)
    assert "Angry Alex" in (task.path / "instruction.md").read_text()

    rubric = tomllib.loads((task.path / "tests" / "rubric.toml").read_text())
    assert rubric["criterion"][0]["id"] == str(sim_rows.metric.id)
    assert rubric["criterion"][0]["type"] == "numeric"


def test_export_tasks_rejects_missing_scenarios(db_session, sim_rows, harbor_work_dir):
    sim_rows.run.scenario_ids = [str(sim_rows.persona.id)]  # not a scenario id
    with pytest.raises(ValueError, match="not found"):
        export_tasks(db_session, run=sim_rows.run, agent=sim_rows.agent, metrics=[])


def test_exported_task_loads_in_harbor(db_session, sim_rows, harbor_work_dir):
    task_mod = pytest.importorskip("harbor.models.task.task")
    [task] = export_tasks(
        db_session, run=sim_rows.run, agent=sim_rows.agent, metrics=[sim_rows.metric]
    )

    harbor_task = task_mod.Task(task.path)
    assert harbor_task.config.metadata["scenario_id"] == str(sim_rows.scenario.id)
    assert harbor_task.instruction.strip()
