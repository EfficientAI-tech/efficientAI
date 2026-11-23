"""Celery task: run one red team (recon, attack levels, report)."""

from uuid import UUID

from loguru import logger

from app.workers.config import celery_app


@celery_app.task(
    name="run_red_team",
    bind=True,
    time_limit=4 * 60 * 60,
    soft_time_limit=4 * 60 * 60 - 120,
)
def run_red_team_task(self, red_team_run_id: str):
    from app.services.red_team.orchestrator import run_red_team

    logger.info("[RedTeam] Task {} starting run {}", self.request.id, red_team_run_id)
    run_red_team(UUID(red_team_run_id))
    return {"red_team_run_id": red_team_run_id}
