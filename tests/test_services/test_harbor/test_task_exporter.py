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


def test_export_tasks_per_scenario_rubric(db_session, sim_rows, harbor_work_dir):
    from app.models.database import Metric, Scenario
    from app.services.metrics.scenario_scope import replace_metric_scenarios

    scenario_b = Scenario(
        organization_id=sim_rows.agent.organization_id,
        workspace_id=sim_rows.agent.workspace_id,
        agent_id=sim_rows.agent.id,
        name="Billing dispute",
        description="Customer disputes a charge.",
    )
    only_b = Metric(
        organization_id=sim_rows.metric.organization_id,
        workspace_id=sim_rows.metric.workspace_id,
        name="Offered credit",
        description="Did the agent offer account credit?",
        metric_type="boolean",
    )
    db_session.add_all([scenario_b, only_b])
    db_session.flush()
    replace_metric_scenarios(
        db_session,
        organization_id=sim_rows.metric.organization_id,
        metric=only_b,
        scenario_ids=[scenario_b.id],
    )
    sim_rows.run.scenario_ids = [str(sim_rows.scenario.id), str(scenario_b.id)]
    db_session.commit()

    tasks = export_tasks(
        db_session,
        run=sim_rows.run,
        agent=sim_rows.agent,
        metrics=[sim_rows.metric, only_b],
    )
    assert len(tasks) == 2
    rubrics = {
        t.scenario_id: tomllib.loads((t.path / "tests" / "rubric.toml").read_text())
        for t in tasks
    }
    ids_a = {c["id"] for c in rubrics[sim_rows.scenario.id]["criterion"]}
    ids_b = {c["id"] for c in rubrics[scenario_b.id]["criterion"]}
    assert str(sim_rows.metric.id) in ids_a
    assert str(only_b.id) not in ids_a
    assert str(only_b.id) in ids_b
    assert str(sim_rows.metric.id) in ids_b


def test_exported_task_loads_in_harbor(db_session, sim_rows, harbor_work_dir):
    task_mod = pytest.importorskip("harbor.models.task.task")
    [task] = export_tasks(
        db_session, run=sim_rows.run, agent=sim_rows.agent, metrics=[sim_rows.metric]
    )

    harbor_task = task_mod.Task(task.path)
    assert harbor_task.config.metadata["scenario_id"] == str(sim_rows.scenario.id)
    assert harbor_task.instruction.strip()
