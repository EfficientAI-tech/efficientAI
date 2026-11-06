"""Harbor job entry point, run as a subprocess by ``run_harbor_simulation``.

    python -m app.services.harbor.job_runner <simulation_run_id>

A separate process keeps Harbor's asyncio runtime and logging handlers out of the
Celery worker, and lets the worker cancel a run with SIGINT.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.harbor.task_exporter import run_work_dir

AGENT_IMPORT_PATH = "app.services.harbor.conversation_agent:EfficientAIConversationAgent"
ENVIRONMENT_IMPORT_PATH = "app.services.harbor.noop_environment:NoopEnvironment"
VERIFIER_IMPORT_PATH = "app.services.harbor.metric_verifier:EfficientAIMetricVerifier"
JOBS_DIR_NAME = "jobs"


def harbor_job_name(run) -> str:
    return f"run-{run.run_id}"


def harbor_job_dir(run) -> Path:
    return run_work_dir(run) / JOBS_DIR_NAME / harbor_job_name(run)


def build_job_config(
    run, *, task_paths: list[Path], production_model: str | None
) -> dict[str, Any]:
    agent_kwargs = {
        "simulation_run_id": str(run.id),
        "production_llm_provider": run.production_llm_provider,
        "production_llm_model": run.production_llm_model,
        "test_llm_provider": run.test_llm_provider,
        "test_llm_model": run.test_llm_model,
    }
    return {
        "job_name": harbor_job_name(run),
        "jobs_dir": str(run_work_dir(run) / JOBS_DIR_NAME),
        "n_attempts": run.n_attempts,
        "n_concurrent_trials": run.n_concurrent,
        "retry": {"max_retries": 1},
        "quiet": True,
        "tasks": [{"path": str(path)} for path in task_paths],
        "agents": [
            {
                "import_path": AGENT_IMPORT_PATH,
                "model_name": production_model,
                "kwargs": {k: v for k, v in agent_kwargs.items() if v is not None},
            }
        ],
        "environment": {"import_path": ENVIRONMENT_IMPORT_PATH},
        "verifier": {
            "import_path": VERIFIER_IMPORT_PATH,
            "kwargs": {"simulation_run_id": str(run.id), "pass_threshold": run.pass_threshold},
        },
    }


def production_model_label(run, agent) -> str | None:
    if run.production_llm_provider and run.production_llm_model:
        return f"{run.production_llm_provider}/{run.production_llm_model}"
    provider = getattr(agent.main_llm_provider, "value", agent.main_llm_provider)
    if provider and agent.main_llm_model:
        return f"{provider}/{agent.main_llm_model}"
    return None


async def run_job(simulation_run_id: UUID) -> None:
    from harbor.job import Job
    from harbor.models.job.config import JobConfig

    from app.database import SessionLocal
    from app.models.database import Agent, SimulationRun

    db = SessionLocal()
    try:
        run = db.query(SimulationRun).filter(SimulationRun.id == simulation_run_id).one()
        agent = db.query(Agent).filter(Agent.id == run.agent_id).one()
        tasks_root = run_work_dir(run) / "tasks"
        task_paths = sorted(p for p in tasks_root.iterdir() if p.is_dir())
        config = build_job_config(
            run,
            task_paths=task_paths,
            production_model=production_model_label(run, agent),
        )
    finally:
        db.close()

    job = await Job.create(JobConfig.model_validate(config))
    await job.run()


def load_runtime_config() -> None:
    """Load config.yml like Celery workers do (``app/workers/config.py``).

    This process never imports the Celery app, so without this it would only see
    ``.env`` (e.g. the docker-compose ``db`` host) instead of the configured database.
    """
    import os

    from app.config import load_config_from_file

    config_path = Path(os.environ.get("EFFICIENTAI_CONFIG_PATH", "config.yml"))
    if config_path.exists():
        load_config_from_file(str(config_path))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: python -m app.services.harbor.job_runner <simulation_run_id>", file=sys.stderr
        )
        return 2
    load_runtime_config()
    asyncio.run(run_job(UUID(argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
