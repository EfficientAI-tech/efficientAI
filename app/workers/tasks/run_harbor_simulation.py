"""Celery task: run a Harbor simulation job (scenarios × personas × attempts)."""

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.models.database import Agent, SimulationRun, SimulationRunStatus
from app.workers.config import celery_app

_POLL_SECONDS = 5
_CANCEL_GRACE_SECONDS = 30
_LOG_TAIL_CHARS = 2000
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _log_tail(path: Path) -> str:
    try:
        return path.read_text(errors="replace")[-_LOG_TAIL_CHARS:]
    except OSError:
        return ""


def _stop_process(proc: subprocess.Popen) -> None:
    """SIGINT lets Harbor cancel trials and write job results; SIGKILL after a grace period."""
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=_CANCEL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@celery_app.task(
    name="run_harbor_simulation",
    bind=True,
    time_limit=6 * 60 * 60,
    soft_time_limit=6 * 60 * 60 - 120,
)
def run_harbor_simulation_task(self, simulation_run_id: str):
    from app.services.harbor.job_runner import harbor_job_dir, harbor_job_name
    from app.services.harbor.result_ingest import (
        archive_run_dir,
        assign_attempt_indexes,
        compute_summary,
        fail_unfinished_trials,
        read_harbor_job_stats,
        refresh_run_progress,
        trial_results,
    )
    from app.services.harbor.task_exporter import export_tasks, run_work_dir
    from app.workers.tasks.process_evaluator_result import select_metrics_for_evaluation

    db = SessionLocal()
    run_uuid = UUID(simulation_run_id)
    try:
        run = db.query(SimulationRun).filter(SimulationRun.id == run_uuid).first()
        if not run:
            logger.error(f"[SimulationRun {simulation_run_id}] Not found")
            return {"error": "Simulation run not found"}
        # acks_late + long runs can redeliver this task; only a queued run may start.
        if run.status != SimulationRunStatus.QUEUED.value:
            logger.warning(
                f"[SimulationRun {run.run_id}] Status is {run.status}, not starting again"
            )
            return {"status": run.status}

        run.status = SimulationRunStatus.PREPARING.value
        run.celery_task_id = self.request.id
        run.started_at = datetime.now(timezone.utc)
        db.commit()

        cancelled = False
        returncode = None
        proc: subprocess.Popen | None = None
        log_path = run_work_dir(run) / "harbor.log"
        try:
            agent = db.query(Agent).filter(Agent.id == run.agent_id).one()
            metrics = select_metrics_for_evaluation(
                db,
                organization_id=run.organization_id,
                agent=agent,
                metric_ids=run.metric_ids,
                workspace_id=run.workspace_id,
            )
            tasks = export_tasks(db, run=run, agent=agent, metrics=metrics)
            run.expected_trials = len(tasks) * run.n_attempts
            run.harbor_job_name = harbor_job_name(run)
            run.status = SimulationRunStatus.RUNNING.value
            db.commit()
            logger.info(
                f"[SimulationRun {run.run_id}] Exported {len(tasks)} tasks; "
                f"starting Harbor job ({run.expected_trials} trials)"
            )

            from app.workers.config import _config_path

            env = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    filter(None, [str(_PROJECT_ROOT), os.environ.get("PYTHONPATH")])
                ),
                # Same config.yml this worker loaded (job_runner loads it before any DB use).
                "EFFICIENTAI_CONFIG_PATH": str(_config_path.resolve()),
            }
            with open(log_path, "w") as log_file:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "app.services.harbor.job_runner", str(run.id)],
                    cwd=_PROJECT_ROOT,
                    env=env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
                while proc.poll() is None:
                    time.sleep(_POLL_SECONDS)
                    db.refresh(run)
                    refresh_run_progress(db, run)
                    db.commit()
                    if run.cancel_requested and not cancelled:
                        logger.info(f"[SimulationRun {run.run_id}] Cancelling Harbor job")
                        cancelled = True
                        _stop_process(proc)
                returncode = proc.returncode

            run.status = SimulationRunStatus.INGESTING.value
            db.commit()

            results = trial_results(db, run.id)
            assign_attempt_indexes(results)
            fail_unfinished_trials(
                results,
                "Trial cancelled" if cancelled else "Trial did not finish (see Harbor job log)",
            )
            summary = compute_summary(db, run, results)
            summary["harbor"] = read_harbor_job_stats(harbor_job_dir(run))
            run.summary = summary
            refresh_run_progress(db, run)
            if run.failed_trials and not run.error_message:
                preview = (summary.get("failed_trial_errors") or [{}])[0].get("error_message")
                if preview:
                    run.error_message = (
                        f"{run.failed_trials} trial(s) failed. First error: {preview[:2000]}"
                    )
            db.commit()

            try:
                run.artifacts_s3_key = archive_run_dir(run, run_work_dir(run))
            except Exception as archive_err:
                logger.warning(
                    f"[SimulationRun {run.run_id}] Artifact upload failed: {archive_err}"
                )

            if cancelled:
                run.status = SimulationRunStatus.CANCELLED.value
            elif returncode == 0:
                run.status = SimulationRunStatus.COMPLETED.value
            else:
                run.status = SimulationRunStatus.FAILED.value
                run.error_message = f"Harbor exited with code {returncode}:\n{_log_tail(log_path)}"
        except Exception as exc:
            if proc is not None and proc.poll() is None:
                _stop_process(proc)
            db.rollback()
            logger.error(f"[SimulationRun {simulation_run_id}] Failed: {exc}", exc_info=True)
            run = db.query(SimulationRun).filter(SimulationRun.id == run_uuid).first()
            run.status = SimulationRunStatus.FAILED.value
            run.error_message = str(exc)

        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(
            f"[SimulationRun {run.run_id}] {run.status}: "
            f"{run.completed_trials}/{run.expected_trials} completed, {run.failed_trials} failed"
        )
        return {"simulation_run_id": simulation_run_id, "status": run.status}
    finally:
        db.close()
