"""Tests for deferred Flexprice Redis buffer."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.services.billing import flexprice_buffer as buf


class _FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.strings: dict[str, str] = {}

    def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def lpop(self, key: str) -> str | None:
        items = self.lists.get(key) or []
        if not items:
            return None
        return items.pop(0)

    def llen(self, key: str) -> int:
        return len(self.lists.get(key) or [])

    def lindex(self, key: str, index: int) -> str | None:
        items = self.lists.get(key) or []
        if index < 0:
            index = len(items) + index
        if index < 0 or index >= len(items):
            return None
        return items[index]

    def lrem(self, key: str, count: int, value: str) -> int:
        items = self.lists.get(key) or []
        removed = 0
        if count == 0:
            return 0
        kept: list[str] = []
        for item in items:
            if item == value and removed < abs(count):
                removed += 1
                continue
            kept.append(item)
        self.lists[key] = kept
        return removed

    def lmove(self, src: str, dest: str, src_where: str, dest_where: str) -> str | None:
        items = self.lists.get(src) or []
        if not items:
            return None
        value = items.pop(0) if src_where == "LEFT" else items.pop()
        dest_items = self.lists.setdefault(dest, [])
        if dest_where == "LEFT":
            dest_items.insert(0, value)
        else:
            dest_items.append(value)
        return value

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self.strings:
            return None
        self.strings[key] = value
        return True

    def delete(self, key: str) -> int:
        existed = key in self.strings
        self.strings.pop(key, None)
        return 1 if existed else 0


@pytest.fixture
def fake_redis(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr(buf, "_redis", client)
    return client


def test_enqueue_and_flush_round_trip(monkeypatch, fake_redis):
    org_id = uuid4()
    sent: list[tuple] = []

    monkeypatch.setattr(
        "app.services.billing.flexprice_service.disabled_reason",
        lambda: None,
    )

    def _record(event_name, organization_id, event_id, *, properties=None):
        sent.append((event_name, organization_id, event_id, properties))
        return True

    monkeypatch.setattr(
        "app.services.billing.flexprice_service.record_event",
        _record,
    )

    assert buf.enqueue_flexprice_event(
        "call_import.recording_minutes_billed",
        org_id,
        uuid4(),
        properties={"quantity": 2},
    )
    assert fake_redis.llen(buf._QUEUE_KEY) == 1

    stats = buf.flush_buffered_flexprice_events(max_events=10)
    assert stats["flushed"] == 1
    assert stats["pending"] == 0
    assert len(sent) == 1


def test_flush_keeps_inflight_until_ingest_succeeds(monkeypatch, fake_redis):
    org_id = uuid4()
    monkeypatch.setattr(
        "app.services.billing.flexprice_service.disabled_reason",
        lambda: None,
    )
    outcomes = iter([False, True])

    def _record(*_a, **_k):
        return next(outcomes)

    monkeypatch.setattr(
        "app.services.billing.flexprice_service.record_event",
        _record,
    )
    payload = json.dumps(
        {
            "event_name": "call_import.evaluation_completed",
            "organization_id": str(org_id),
            "event_id": "ev:42",
            "properties": {"quantity": 10},
        }
    )
    fake_redis.rpush(buf._QUEUE_KEY, payload)

    first = buf.flush_buffered_flexprice_events(max_events=1)
    assert first["flushed"] == 0
    assert first["failed"] == 1
    assert fake_redis.llen(buf._QUEUE_KEY) == 1
    assert fake_redis.llen(buf._INFLIGHT_KEY) == 0

    second = buf.flush_buffered_flexprice_events(max_events=1)
    assert second["flushed"] == 1
    assert fake_redis.llen(buf._INFLIGHT_KEY) == 0
    assert buf.pending_event_count() == 0


def test_flush_requeues_on_ingest_failure(monkeypatch, fake_redis):
    org_id = uuid4()
    monkeypatch.setattr(
        "app.services.billing.flexprice_service.disabled_reason",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.services.billing.flexprice_service.record_event",
        lambda *_a, **_k: False,
    )

    payload = {
        "event_name": "call_import.evaluation_completed",
        "organization_id": str(org_id),
        "event_id": "1:1",
        "properties": {"quantity": 1},
    }
    fake_redis.rpush(buf._QUEUE_KEY, json.dumps(payload))

    stats = buf.flush_buffered_flexprice_events(max_events=1)
    assert stats["flushed"] == 0
    assert stats["failed"] == 1
    assert fake_redis.llen(buf._QUEUE_KEY) == 1
    assert fake_redis.llen(buf._INFLIGHT_KEY) == 0

    monkeypatch.setattr(
        "app.services.billing.flexprice_service.record_event",
        lambda *_a, **_k: True,
    )
    stats = buf.flush_buffered_flexprice_events(max_events=1)
    assert stats["flushed"] == 1
    assert stats["pending"] == 0
    assert fake_redis.llen(buf._INFLIGHT_KEY) == 0
