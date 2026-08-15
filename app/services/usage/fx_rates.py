"""USD/INR display FX rate (Frankfurter v2, cached in Redis)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import redis
from loguru import logger

from app.config import settings

_REDIS_KEY = "usage:fx:USD_INR"
_FRANKFURTER_URL = "https://api.frankfurter.dev/v2/rate/USD/INR"
_DEFAULT_RATE = 83.0
_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _cache_payload(rate: float, as_of: datetime, source: str) -> dict[str, Any]:
    return {
        "base": "USD",
        "quote": "INR",
        "rate": rate,
        "as_of": as_of.astimezone(timezone.utc).isoformat(),
        "source": source,
    }


def _read_cached() -> Optional[dict[str, Any]]:
    try:
        raw = _client().get(_REDIS_KEY)
        if not raw:
            return None
        payload = json.loads(raw)
        if not isinstance(payload.get("rate"), (int, float)):
            return None
        return payload
    except (redis.RedisError, json.JSONDecodeError):
        return None


def get_usd_inr_rate() -> dict[str, Any]:
    cached = _read_cached()
    if cached is not None:
        return cached
    return _cache_payload(_DEFAULT_RATE, datetime.now(timezone.utc), "default")


def refresh_usd_inr_rate() -> dict[str, Any]:
    rate = _DEFAULT_RATE
    as_of = datetime.now(timezone.utc)
    source = "default"
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(_FRANKFURTER_URL)
            response.raise_for_status()
            data = response.json()
            fetched = float(data["rate"])
            if fetched > 0:
                rate = fetched
                source = "frankfurter"
                as_of = datetime.fromisoformat(data["date"]).replace(tzinfo=timezone.utc)
    except Exception as exc:
        logger.warning("USD/INR FX refresh failed, using fallback: {}", exc)

    payload = _cache_payload(rate, as_of, source)
    try:
        _client().set(_REDIS_KEY, json.dumps(payload), ex=25 * 3600)
    except redis.RedisError as exc:
        logger.warning("USD/INR FX cache write failed: {}", exc)
    return payload
