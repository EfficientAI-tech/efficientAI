"""Bounded per-process catalog cache: TTL, sweep-on-write and LRU size cap."""

import threading

import pytest

from app.config import settings
from app.workers import catalog_cache
from app.workers.catalog_cache import (
    cached_catalog_fetch,
    catalog_cache_size,
    clear_worker_catalog_cache,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(catalog_cache.time, "monotonic", clock)
    monkeypatch.setattr(settings, "CATALOG_CACHE_MAX_ENTRIES", 2048, raising=False)
    monkeypatch.setattr(settings, "CATALOG_CACHE_SWEEP_SECONDS", 30.0, raising=False)
    clear_worker_catalog_cache()
    yield clock
    clear_worker_catalog_cache()


def _fetch(key, value="v", ttl=120.0, calls=None):
    def _load():
        if calls is not None:
            calls.append(key)
        return value

    return cached_catalog_fetch("ns", key, _load, ttl_seconds=ttl)


def test_hit_within_ttl_and_reload_after_expiry(clock):
    calls = []
    assert _fetch("a", "v1", calls=calls) == "v1"
    clock.now += 119
    assert _fetch("a", "v2", calls=calls) == "v1"
    clock.now += 1
    assert _fetch("a", "v2", calls=calls) == "v2"
    assert calls == ["a", "a"]


def test_each_entry_keeps_its_own_ttl(clock):
    _fetch("short", ttl=10)
    _fetch("long", ttl=600)
    clock.now += 300
    calls = []
    _fetch("short", calls=calls, ttl=10)
    _fetch("long", calls=calls, ttl=600)
    assert calls == ["short"]


def test_sweep_drops_expired_keys_that_are_never_read_again(clock):
    """Old version keys / finished evaluations must not stay in memory."""
    for i in range(50):
        _fetch(f"old-version-{i}", ttl=120)
    assert catalog_cache_size() == 50

    clock.now += 121  # all expired, but nobody reads those keys again
    _fetch("new-version")

    assert catalog_cache_size() == 1


def test_sweep_runs_at_most_once_per_interval(clock):
    _fetch("first", ttl=5)  # first write sweeps and stamps the time
    _fetch("a", ttl=5)
    clock.now += 10  # "a" and "first" expired, but only 10s since the sweep
    _fetch("b", ttl=600)
    assert catalog_cache_size() == 3

    clock.now += 25  # 35s since the last sweep
    _fetch("c", ttl=600)
    assert catalog_cache_size() == 2  # "b" and "c" remain


def test_size_cap_evicts_least_recently_used(clock, monkeypatch):
    monkeypatch.setattr(settings, "CATALOG_CACHE_MAX_ENTRIES", 3, raising=False)
    _fetch("a")
    _fetch("b")
    _fetch("c")
    _fetch("a")  # hit: "a" becomes most recently used
    _fetch("d")  # evicts "b", the least recently used

    assert catalog_cache_size() == 3
    calls = []
    for key in ("a", "c", "d", "b"):
        _fetch(key, calls=calls)
    assert calls == ["b"]


def test_cap_holds_under_a_burst_of_fresh_entries(clock, monkeypatch):
    monkeypatch.setattr(settings, "CATALOG_CACHE_MAX_ENTRIES", 100, raising=False)
    for i in range(1000):
        _fetch(f"k{i}", ttl=600)
    assert catalog_cache_size() == 100


def test_zero_ttl_is_not_cached(clock):
    calls = []
    _fetch("a", ttl=0, calls=calls)
    _fetch("a", ttl=0, calls=calls)
    assert calls == ["a", "a"]
    assert catalog_cache_size() == 0


def test_concurrent_threads_stay_within_cap(clock, monkeypatch):
    monkeypatch.setattr(settings, "CATALOG_CACHE_MAX_ENTRIES", 64, raising=False)
    errors = []

    def _worker(n):
        try:
            for i in range(500):
                _fetch(f"t{n}-{i % 100}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(n,)) for n in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert catalog_cache_size() <= 64


def test_eval_snapshot_ttl_defaults_to_ten_minutes(monkeypatch):
    from app.workers.tasks import evaluate_call_import_row_core as core

    assert settings.EVAL_SNAPSHOT_CACHE_TTL_SECONDS == 600
    assert core._snapshot_cache_ttl_seconds() == 600.0
    monkeypatch.setattr(settings, "EVAL_SNAPSHOT_CACHE_TTL_SECONDS", 900)
    assert core._snapshot_cache_ttl_seconds() == 900.0
