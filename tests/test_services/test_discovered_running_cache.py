"""Discovery reads scan completed rows once, then use the Redis aggregate."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import redis

from app.api.v1.routes.call_import_evaluations import (
    _get_running_discovered_metrics,
)
from app.services.call_imports.discovered_running_cache import (
    _RedisLock,
    _lock_key,
    _ready_key,
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

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(str(field))

    def hset(self, key, field=None, value=None, mapping=None):
        bucket = self.hashes.setdefault(key, {})
        if mapping:
            bucket.update({str(name): str(item) for name, item in mapping.items()})
        elif field is not None:
            bucket[str(field)] = value
        return 1

    def hdel(self, key, *fields):
        bucket = self.hashes.get(key, {})
        for field in fields:
            bucket.pop(str(field), None)
        return len(fields)

    def expire(self, key, _ttl):
        return True

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def sadd(self, key, *members):
        self.sets.setdefault(key, set()).update(str(member) for member in members)
        return len(members)

    def srem(self, key, *members):
        bucket = self.sets.get(key, set())
        for member in members:
            bucket.discard(str(member))
        return len(members)

    def eval(self, script, _numkeys, key, token, *_args):
        if self.values.get(key) != token:
            return 0
        if "del" in script:
            self.values.pop(key, None)
            return 1
        return 1


def _patch_redis(monkeypatch, fake):
    monkeypatch.setattr(
        "app.services.call_imports.discovered_running_cache._get_redis",
        lambda: fake,
    )


def test_second_cached_discovery_read_does_not_scan_rows(monkeypatch):
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)
    scans = {"n": 0}
    evaluation_id = uuid4()
    seeded_row_id = uuid4()

    def _load(_db, _evaluation_id):
        scans["n"] += 1
        return [
            SimpleNamespace(
                id=seeded_row_id,
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
        uuid4(),
        {
            "__discovered_metrics__": [
                {"key": "hold_time", "name": "Hold time"}
            ]
        },
    )
    second = _get_running_discovered_metrics(None, evaluation_id, from_cache=True)
    record_row_discoveries(
        evaluation_id,
        seeded_row_id,
        {
            "__discovered_metrics__": [
                {"key": "hold_time", "name": "Hold time", "count": 1}
            ]
        },
    )
    third = _get_running_discovered_metrics(None, evaluation_id, from_cache=True)

    assert scans["n"] == 1
    assert first[0]["key"] == "hold_time"
    assert first[0]["count"] == 1
    assert second[0]["count"] == 2
    assert third[0]["count"] == 2


def test_rescore_replaces_that_rows_discoveries(monkeypatch):
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)
    evaluation_id = uuid4()
    row_id = uuid4()

    monkeypatch.setattr(
        "app.db_sharding.eval_rows.load_evaluation_rows_for_run",
        lambda _db, _evaluation_id: [
            SimpleNamespace(
                id=row_id,
                status="completed",
                metric_scores={
                    "__discovered_metrics__": [
                        {"key": "hold_time", "name": "Hold time"}
                    ]
                },
            )
        ],
    )

    _get_running_discovered_metrics(None, evaluation_id, from_cache=True)
    record_row_discoveries(
        evaluation_id,
        row_id,
        {
            "__discovered_metrics__": [
                {"key": "refund_delay", "name": "Refund delay"}
            ]
        },
    )
    current = _get_running_discovered_metrics(None, evaluation_id, from_cache=True)

    assert [item["key"] for item in current] == ["refund_delay"]
    assert current[0]["count"] == 1


def test_missed_lock_marks_the_cache_incomplete(monkeypatch):
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)
    scans = {"n": 0}
    evaluation_id = uuid4()
    payloads = [
        {
            "__discovered_metrics__": [
                {"key": "hold_time", "name": "Hold time"}
            ]
        },
        {
            "__discovered_metrics__": [
                {"key": "refund_delay", "name": "Refund delay"}
            ]
        },
    ]

    def _load(_db, _evaluation_id):
        scores = payloads[min(scans["n"], len(payloads) - 1)]
        scans["n"] += 1
        return [
            SimpleNamespace(
                id=uuid4(),
                status="completed",
                metric_scores=scores,
            )
        ]

    monkeypatch.setattr(
        "app.db_sharding.eval_rows.load_evaluation_rows_for_run",
        _load,
    )

    first = _get_running_discovered_metrics(None, evaluation_id, from_cache=True)
    monkeypatch.setattr(
        "app.services.call_imports.discovered_running_cache._LOCK_WAIT_SECONDS",
        0,
    )
    original_set = fake.set

    def _refuse_lock(key, value, nx=False, ex=None):
        if nx:
            return False
        return original_set(key, value, nx=nx, ex=ex)

    fake.set = _refuse_lock
    record_row_discoveries(
        evaluation_id,
        uuid4(),
        payloads[1],
    )
    assert fake.get(_ready_key(evaluation_id)) is None

    fake.set = original_set
    second = _get_running_discovered_metrics(None, evaluation_id, from_cache=True)

    assert scans["n"] == 2
    assert first[0]["key"] == "hold_time"
    assert second[0]["key"] == "refund_delay"


def test_redis_error_marks_the_cache_incomplete(monkeypatch):
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)
    scans = {"n": 0}
    evaluation_id = uuid4()

    def _load(_db, _evaluation_id):
        scans["n"] += 1
        return [
            SimpleNamespace(
                id=uuid4(),
                status="completed",
                metric_scores={
                    "__discovered_metrics__": [
                        {"key": "hold_time", "name": "Hold time"}
                    ]
                },
            )
        ]

    monkeypatch.setattr(
        "app.db_sharding.eval_rows.load_evaluation_rows_for_run",
        _load,
    )
    _get_running_discovered_metrics(None, evaluation_id, from_cache=True)
    real_hset = fake.hset

    def _boom(*_args, **_kwargs):
        raise redis.RedisError("redis down")

    fake.hset = _boom
    record_row_discoveries(
        evaluation_id,
        uuid4(),
        {
            "__discovered_metrics__": [
                {"key": "refund_delay", "name": "Refund delay"}
            ]
        },
    )
    assert fake.get(_ready_key(evaluation_id)) is None

    fake.hset = real_hset
    _get_running_discovered_metrics(None, evaluation_id, from_cache=True)
    assert scans["n"] == 2


def test_lock_release_keeps_another_owners_token():
    fake = _FakeRedis()
    evaluation_id = uuid4()
    lock = _RedisLock(fake, evaluation_id)
    lock.__enter__()
    key = _lock_key(evaluation_id)
    fake.values[key] = "someone-else"
    lock.__exit__()

    assert fake.values[key] == "someone-else"


def test_seed_renews_the_lock_while_writing_rows(monkeypatch):
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)
    renews = {"n": 0}
    real_renew = _RedisLock.renew

    def _count(self):
        renews["n"] += 1
        return real_renew(self)

    monkeypatch.setattr(_RedisLock, "renew", _count)
    monkeypatch.setattr(
        "app.db_sharding.eval_rows.load_evaluation_rows_for_run",
        lambda _db, _evaluation_id: [
            SimpleNamespace(
                id=uuid4(),
                status="completed",
                metric_scores={
                    "__discovered_metrics__": [
                        {"key": "hold_time", "name": "Hold time"}
                    ]
                },
            )
        ],
    )

    found = _get_running_discovered_metrics(None, uuid4(), from_cache=True)

    assert found[0]["key"] == "hold_time"
    assert renews["n"] >= 1
