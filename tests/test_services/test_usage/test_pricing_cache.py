"""Tests for Redis-backed usage pricing cache."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import app.services.usage.pricing_cache as pricing_cache_mod


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def setex(self, key: str, _ttl: int, value: str):
        self.store[key] = value

    def scan(self, cursor: int, match: str, count: int):
        keys = [key for key in self.store if key.startswith(match.rstrip("*"))]
        return 0, keys

    def delete(self, *keys: str):
        for key in keys:
            self.store.pop(key, None)


def test_pricing_cache_roundtrip(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(pricing_cache_mod, "_client", lambda: fake)

    org_id = uuid4()
    key = pricing_cache_mod.pricing_cache_key(
        organization_id=org_id,
        model="gpt-4o",
        usage_kind="llm",
        usage_date=date(2026, 8, 13),
    )
    payload = {
        "source": "catalog",
        "rate_id": str(uuid4()),
        "input_micro_usd_per_million": 2_500_000,
        "output_micro_usd_per_million": 10_000_000,
        "cache_read_micro_usd_per_million": 0,
        "cache_creation_micro_usd_per_million": 0,
        "reasoning_micro_usd_per_million": 0,
        "audio_micro_usd_per_second": 0,
        "tts_micro_usd_per_million_chars": 0,
    }
    pricing_cache_mod.set_cached_rate_payload(key, payload)
    cached = pricing_cache_mod.get_cached_rate_payload(key)
    assert cached == payload


def test_pricing_cache_null_marker(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(pricing_cache_mod, "_client", lambda: fake)

    org_id = uuid4()
    key = pricing_cache_mod.pricing_cache_key(
        organization_id=org_id,
        model="unknown-model",
        usage_kind="llm",
        usage_date=date(2026, 8, 13),
    )
    pricing_cache_mod.set_cached_rate_payload(key, None)
    assert pricing_cache_mod.get_cached_rate_payload(key) == {}


def test_null_cache_uses_shorter_ttl(monkeypatch):
    fake = _FakeRedis()
    recorded: list[tuple[int, str]] = []

    def _setex(key: str, ttl: int, value: str):
        fake.store[key] = value
        recorded.append((ttl, value))

    fake.setex = _setex  # type: ignore[method-assign]
    monkeypatch.setattr(pricing_cache_mod, "_client", lambda: fake)

    key = "usage:pricing:test"
    pricing_cache_mod.set_cached_rate_payload(key, None)
    pricing_cache_mod.set_cached_rate_payload(
        key + ":hit",
        {"source": "catalog", "rate_id": str(uuid4())},
    )
    assert recorded[0][0] == pricing_cache_mod.PRICING_NULL_CACHE_TTL_SEC
    assert recorded[0][1] == "__null__"
    assert recorded[1][0] == pricing_cache_mod.PRICING_CACHE_TTL_SEC
