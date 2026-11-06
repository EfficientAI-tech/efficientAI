"""Tests for shared import retry backoff helpers."""

from __future__ import annotations

from app.workers.concurrency.import_retry_backoff import (
    import_dispatch_at_capacity_countdown,
    import_transient_retry_countdown,
)


class _RetryAfterExc(Exception):
    def __init__(self, seconds: int) -> None:
        super().__init__("rate limited")
        self.retry_after_seconds = seconds


def test_transient_honors_retry_after_on_exception():
    assert import_transient_retry_countdown(_RetryAfterExc(45), attempt=0) == 45


def test_transient_exponential_without_retry_after():
    assert import_transient_retry_countdown(None, attempt=0, base_seconds=15, max_seconds=60) == 15
    assert import_transient_retry_countdown(None, attempt=1, base_seconds=15, max_seconds=60) == 30
    assert import_transient_retry_countdown(None, attempt=2, base_seconds=15, max_seconds=60) == 60
    assert import_transient_retry_countdown(None, attempt=5, base_seconds=15, max_seconds=60) == 60


def test_dispatch_at_capacity_exponential():
    assert import_dispatch_at_capacity_countdown(level=1, base_seconds=15, max_seconds=120) == 15
    assert import_dispatch_at_capacity_countdown(level=2, base_seconds=15, max_seconds=120) == 30
    assert import_dispatch_at_capacity_countdown(level=4, base_seconds=15, max_seconds=120) == 120


def test_dispatch_at_capacity_respects_provider_wait():
    assert import_dispatch_at_capacity_countdown(
        provider_wait_seconds=40,
        level=1,
        base_seconds=15,
        max_seconds=120,
    ) == 40
