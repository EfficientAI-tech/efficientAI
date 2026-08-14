"""Tests for usage pricing Celery queue routing."""

from app.workers.config import USAGE_WORKER_QUEUE, celery_app


def test_flush_usage_counters_routes_to_usage_queue():
    routes = celery_app.conf.task_routes
    assert routes["flush_usage_counters"]["queue"] == USAGE_WORKER_QUEUE


def test_recompute_usage_costs_routes_to_usage_queue():
    routes = celery_app.conf.task_routes
    assert routes["recompute_usage_costs"]["queue"] == USAGE_WORKER_QUEUE


def test_usage_beat_flush_targets_usage_queue():
    schedule = celery_app.conf.beat_schedule["flush-llm-usage-counters"]
    assert schedule["options"]["queue"] == USAGE_WORKER_QUEUE
