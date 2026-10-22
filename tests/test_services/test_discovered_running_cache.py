"""Discovery reads scan completed rows once, then use the Redis aggregate."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.api.v1.routes.call_import_evaluations import (
    _get_running_discovered_metrics,
)
from app.services.call_imports.discovered_running_cache import (
    record_row_discoveries,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
            self.hashes.pop(key, None)
            self.sets.pop(key, None)
        return len(keys)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hset(self, key, mapping=None):
        bucket = self.hashes.setdefault(key, {})
        if mapping:
            bucket.update({str(field): str(value) for field, value in mapping.items()})
        return 1

    def expire(self, key, _ttl):
        return True

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def sadd(self, key, *members):
        self.sets.setdefault(key, set()).update(str(member) for member in members)
        return len(members)


def test_second_cached_discovery_read_does_not_scan_rows(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(
        "app.services.call_imports.discovered_running_cache._get_redis",
        lambda: fake,
    )
    scans = {"n": 0}
    evaluation_id = uuid4()

    def _load(_db, _evaluation_id):
        scans["n"] += 1
        return [
            SimpleNamespace(
                status="completed",
                metric_scores={
                    "__discovered_metrics__": [
                        {"key": "hold_time", "name": "Hold time", "count": 1}
                    ]
                },
            )
        ]

    monkeypatch.setattr(
        "app.db_sharding.eval_rows.load_evaluation_rows_for_run",
        _load,
    )

    first = _get_running_discovered_metrics(None, evaluation_id, from_cache=True)
    record_row_discoveries(
        evaluation_id,
        {
            "__discovered_metrics__": [
                {"key": "hold_time", "name": "Hold time"}
            ]
        },
    )
    second = _get_running_discovered_metrics(None, evaluation_id, from_cache=True)

    assert scans["n"] == 1
    assert first[0]["key"] == "hold_time"
    assert first[0]["count"] == 1
    assert second[0]["count"] == 2
