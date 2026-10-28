"""Tests for deferred Flexprice Redis buffer."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.services.billing import flexprice_buffer as buf


class _FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

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

    def rpoplpush(self, src: str, dest: str) -> str | None:
        items = self.lists.get(src) or []
        if not items:
            return None
        value = items.pop()
        self.lists.setdefault(dest, []).insert(0, value)
        return value


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
