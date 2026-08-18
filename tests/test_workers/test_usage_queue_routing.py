"""Tests for usage pricing Celery queue routing."""

from app.workers.config import PLATFORM_WORKER_QUEUE, USAGE_WORKER_QUEUE, celery_app


def test_flush_usage_counters_routes_to_usage_queue():
    routes = celery_app.conf.task_routes
    assert routes["flush_usage_counters"]["queue"] == USAGE_WORKER_QUEUE


def test_recompute_usage_costs_routes_to_usage_queue():
    routes = celery_app.conf.task_routes
    assert routes["recompute_usage_costs"]["queue"] == USAGE_WORKER_QUEUE


def test_cron_dispatcher_routes_to_default_worker():
    routes = celery_app.conf.task_routes
    assert routes["dispatch_cron_jobs"]["queue"] == "celery"


def test_beat_schedule_includes_platform_tasks():
    schedule = getattr(celery_app.conf, "beat_schedule", None) or {}
    assert schedule["flush-usage-counters"]["task"] == "flush_usage_counters"
    assert schedule["evaluate-alerts"]["task"] == "evaluate_alerts"
    assert schedule["refresh-fx-rates"]["task"] == "refresh_fx_rates"
    assert schedule["prune-oss-usage-history"]["task"] == "prune_oss_usage_history"


def test_platform_tasks_route_to_platform_queue():
    routes = celery_app.conf.task_routes
    assert routes["evaluate_alerts"]["queue"] == PLATFORM_WORKER_QUEUE
    assert routes["refresh_fx_rates"]["queue"] == PLATFORM_WORKER_QUEUE
    assert routes["prune_oss_usage_history"]["queue"] == PLATFORM_WORKER_QUEUE
