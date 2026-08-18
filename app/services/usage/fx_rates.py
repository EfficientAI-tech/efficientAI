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
_DEFAULT_RATE = 95.0
_CACHE_TTL_SECONDS = 25 * 3600
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
        if payload.get("source") != "frankfurter":
            return None
        if not isinstance(payload.get("rate"), (int, float)):
            return None
        return payload
    except (redis.RedisError, json.JSONDecodeError) as exc:
        logger.warning("USD/INR FX cache read failed: {}", exc)
        return None


def _write_cached(payload: dict[str, Any]) -> None:
    try:
        _client().set(_REDIS_KEY, json.dumps(payload), ex=_CACHE_TTL_SECONDS)
    except redis.RedisError as exc:
        logger.warning("USD/INR FX cache write failed: {}", exc)


def _parse_frankfurter_payload(data: Any) -> tuple[float, datetime]:
    if not isinstance(data, dict):
        raise ValueError(f"Frankfurter response is not an object: {type(data).__name__}")

    base = data.get("base")
    quote = data.get("quote")
    if base != "USD" or quote != "INR":
        raise ValueError(f"Unexpected Frankfurter pair: {base}/{quote}")

    rate_raw = data.get("rate")
    if not isinstance(rate_raw, (int, float)):
        raise ValueError(f"Frankfurter rate missing or invalid: {rate_raw!r}")

    rate = float(rate_raw)
    if rate <= 0:
        raise ValueError(f"Frankfurter rate must be positive: {rate}")

    date_raw = data.get("date")
    if not isinstance(date_raw, str) or not date_raw.strip():
        raise ValueError(f"Frankfurter date missing or invalid: {date_raw!r}")

    as_of = datetime.fromisoformat(date_raw).replace(tzinfo=timezone.utc)
    return rate, as_of


def _fallback_payload(reason: str, *, response_body: Any = None) -> dict[str, Any]:
    logger.error(
        "USD/INR FX using hardcoded fallback rate {:.2f} — INR costs may be wrong. reason={} response={}",
        _DEFAULT_RATE,
        reason,
        response_body,
    )
    return _cache_payload(_DEFAULT_RATE, datetime.now(timezone.utc), "default")


def get_usd_inr_rate() -> dict[str, Any]:
    cached = _read_cached()
    if cached is not None:
        return cached
    return refresh_usd_inr_rate()


def refresh_usd_inr_rate() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(_FRANKFURTER_URL)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        return _fallback_payload(f"Frankfurter request failed: {exc}")

    try:
        rate, as_of = _parse_frankfurter_payload(data)
    except Exception as exc:
        return _fallback_payload(f"Frankfurter response parse failed: {exc}", response_body=data)

    payload = _cache_payload(rate, as_of, "frankfurter")
    _write_cached(payload)
    logger.info(
        "USD/INR FX refreshed from Frankfurter: rate={} as_of={}",
        rate,
        as_of.date().isoformat(),
    )
    return payload
