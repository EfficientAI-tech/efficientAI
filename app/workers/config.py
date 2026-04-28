"""Celery application configuration and creation."""

from pathlib import Path

from celery import Celery
from loguru import logger

from app.config import settings, load_config_from_file

# Load config.yml if it exists (before using settings)
# This ensures the Celery worker has the same configuration as the main app
_config_path = Path("config.yml")
if _config_path.exists():
    try:
        load_config_from_file(str(_config_path))
        logger.info(f"✅ Celery worker loaded configuration from {_config_path}")
    except Exception as e:
        logger.warning(f"⚠️  Celery worker: Could not load config.yml: {e}")

# Create Celery app
celery_app = Celery(
    "efficientai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
)

# Route the CSV-driven call-import task to its own queue so a large import
# fan-out can't starve the default queue (synthetic calling, audio gen, evals).
# All other tasks remain on the default queue, so existing behavior is unchanged.
celery_app.conf.task_routes = {
    "process_call_import_row": {"queue": "imports"},
}
