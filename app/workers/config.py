"""Celery application configuration and creation.

Important: this module is imported via ``celery -A app.workers.celery_app``
*before* any task module touches torch / numpy / librosa, so it is the
right place to enforce single-threaded BLAS/OMP/MKL.

Why this matters: the default ``worker`` service runs the audio metric path
(``evaluate_call_import_row_audio`` → Praat / UTMOS / qualitative voice service)
on the ``audio-metrics`` queue. That path transitively loads torch, torchaudio,
librosa, transformers, and speechbrain into each prefork child. With Celery's
default prefork pool and ``--concurrency=N`` on an N-vCPU box, each child opens
up an OpenMP threadpool of size N, so the worker ends up with N×N native threads
fighting over shared OMP/MKL locks. After a handful of tasks one child
inevitably deadlocks inside ``pthread_cond_wait`` in libgomp, Celery
keeps thinking it's healthy, and the queue wedges. ``worker-imports`` (threads,
I/O + LLM only) should not load torch after the audio split.

The mitigations applied here are the canonical Celery + PyTorch
hardening:

* Cap BLAS/OMP/MKL threads to 1 *before* torch et al. get imported.
* ``worker_prefetch_multiplier = 1`` so a wedged child can hold at most
  one task hostage instead of pre-reserving four.
* ``task_acks_late = True`` so a task killed by ``task_time_limit`` or
  ``worker_max_tasks_per_child`` gets redelivered to a healthy child
  instead of being silently lost.
* ``worker_max_tasks_per_child`` recycles children periodically so any
  leaked torch threads / model memory get released.
"""

from __future__ import annotations

import os
from pathlib import Path

# Single-threaded BLAS / OMP for every library that links against them.
# These must be set BEFORE numpy / torch / librosa / transformers / speechbrain
# are imported — once a library has created its OpenMP threadpool, changing
# the env var has no effect. Setting setdefault keeps any operator override
# (e.g. via the container env) intact.
for _var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
):
    os.environ.setdefault(_var, "1")

# HuggingFace tokenizers warn (and occasionally deadlock) when forked after
# their fast-tokenizer threadpool has been created. Disable explicitly.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from celery import Celery  # noqa: E402  (env vars must be set first)
from celery.schedules import crontab  # noqa: E402
from loguru import logger  # noqa: E402

from app.config import settings, load_config_from_file  # noqa: E402

# Load config.yml if it exists (before using settings)
# This ensures the Celery worker has the same configuration as the main app
_config_path = Path("config.yml")
if _config_path.exists():
    try:
        load_config_from_file(str(_config_path))
        logger.info(f"✅ Celery worker loaded configuration from {_config_path}")
    except Exception as e:
        logger.warning(f"⚠️  Celery worker: Could not load config.yml: {e}")

from app.services.billing.flexprice_service import log_startup_status  # noqa: E402

log_startup_status(component="celery-worker")

# Queues consumed by the dedicated call-import / evaluation worker.
IMPORTS_WORKER_QUEUES = "imports,diarization,eval-control,evaluations"
EVAL_CONTROL_QUEUE = "eval-control"
USAGE_WORKER_QUEUE = "usage"
PLATFORM_WORKER_QUEUE = "platform"


def _usage_flush_beat_seconds() -> float:
    raw = os.environ.get("USAGE_FLUSH_BEAT_SECONDS", "120")
    try:
        return max(30.0, float(raw))
    except (TypeError, ValueError):
        return 120.0


def _cron_dispatch_beat_seconds() -> float:
    raw = os.environ.get("CRON_DISPATCH_INTERVAL_SECONDS", "30")
    try:
        return max(10.0, float(raw))
    except (TypeError, ValueError):
        return 30.0


def _platform_beat_schedule() -> dict:
    """Periodic platform tasks — run from dedicated ``celery beat`` (single replica)."""
    return {
        "flush-usage-counters": {
            "task": "flush_usage_counters",
            "schedule": _usage_flush_beat_seconds(),
        },
        "dispatch-cron-jobs": {
            "task": "dispatch_cron_jobs",
            "schedule": _cron_dispatch_beat_seconds(),
        },
        "evaluate-alerts": {
            "task": "evaluate_alerts",
            "schedule": crontab(minute="*/5"),
        },
        "refresh-fx-rates": {
            "task": "refresh_fx_rates",
            "schedule": crontab(hour=6, minute=0),
        },
        "prune-oss-usage-history": {
            "task": "prune_oss_usage_history",
            "schedule": crontab(hour=3, minute=0),
        },
    }


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
    # Long-running ML tasks (audio metrics, evaluations) tolerate prefork
    # poorly. Prefetch=1 means a stuck child only blocks the one task it's
    # currently working on; remaining tasks stay in the broker and get picked
    # up by other healthy children. Default of 4 means a stuck child silently
    # holds 4 reserved tasks hostage.
    worker_prefetch_multiplier=1,
    # Acknowledge tasks only after they finish, so a task killed by the time
    # limit (or by worker_max_tasks_per_child recycling a stuck child) is
    # redelivered rather than lost.
    task_acks_late=True,
    # Recycle prefork children every N tasks. This frees torch model memory,
    # any leaked OMP threads, and HuggingFace tokenizer state, and prevents
    # slow drift from accumulating over hours of import processing.
    worker_max_tasks_per_child=20,
    beat_schedule=_platform_beat_schedule(),
)

# Route call-import recording fetch to the imports queue (preferred by workers
# that consume ``imports,diarization,eval-control,evaluations``). Diarisation
# work (manual bulk transcribe and eval-chain transcribe) goes to the
# diarization queue. Bulk eval control (materialize, cancel, retry) goes to
# ``eval-control`` so operator actions are not head-of-line blocked by scoring.
# Eval fair dispatch and LLM scoring go to the evaluations queue.
celery_app.conf.task_routes = {
    "process_call_import_row": {"queue": "imports"},
    "bulk_diarize_call_import": {"queue": "imports"},
    "bulk_delete_call_import_rows": {"queue": "imports"},
    "materialize_call_import_rows": {"queue": "imports"},
    "delete_call_import": {"queue": "imports"},
    "materialize_call_import_evaluation": {"queue": EVAL_CONTROL_QUEUE},
    "materialize_mapped_call_import_evaluation": {"queue": EVAL_CONTROL_QUEUE},
    "retry_call_import_evaluation": {"queue": EVAL_CONTROL_QUEUE},
    "cancel_call_import_evaluation": {"queue": EVAL_CONTROL_QUEUE},
    "evaluate_call_import_row": {"queue": "evaluations"},
    "evaluate_call_import_row_audio": {"queue": "audio-metrics"},
    "transcribe_call_import_row": {"queue": "diarization"},
    "dispatch_evaluation_rows": {"queue": "evaluations"},
    "dispatch_fair_eval_rows": {"queue": "evaluations"},
    "dispatch_fair_diarization_rows": {"queue": "diarization"},
    "dispatch_fair_import_rows": {"queue": "imports"},
    "generate_evaluation_tldr_insights": {"queue": "evaluations"},
    "generate_evaluation_user_insights": {"queue": "evaluations"},
    "generate_evaluation_metric_clusters": {"queue": "evaluations"},
    "generate_evaluator_result_metric_clusters": {"queue": "evaluations"},
    "generate_evaluation_prompt_improvements": {"queue": "evaluations"},
    "evaluate_studio_run_item": {"queue": "evaluations"},
    "generate_agent_flowchart": {"queue": "celery"},
    "map_agent_flowchart_prompt_sections": {"queue": "celery"},
    "flush_usage_counters": {"queue": USAGE_WORKER_QUEUE},
    "recompute_usage_costs": {"queue": USAGE_WORKER_QUEUE},
    "evaluate_alerts": {"queue": PLATFORM_WORKER_QUEUE},
    "refresh_fx_rates": {"queue": PLATFORM_WORKER_QUEUE},
    "prune_oss_usage_history": {"queue": PLATFORM_WORKER_QUEUE},
    "dispatch_cron_jobs": {"queue": USAGE_WORKER_QUEUE},
    "run_cron_evaluator_job": {"queue": "celery"},
}
