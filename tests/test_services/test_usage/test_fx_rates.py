from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx

from app.services.usage import fx_rates


def test_parse_frankfurter_payload():
    rate, as_of = fx_rates._parse_frankfurter_payload(
        {"date": "2026-08-15", "base": "USD", "quote": "INR", "rate": 95.41}
    )
    assert rate == 95.41
    assert as_of == datetime(2026, 8, 15, tzinfo=timezone.utc)


def test_refresh_caches_live_rate():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "date": "2026-08-15",
        "base": "USD",
        "quote": "INR",
        "rate": 95.41,
    }

    with patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = response
        with patch.object(fx_rates, "_write_cached") as write_cached:
            payload = fx_rates.refresh_usd_inr_rate()

    assert payload["rate"] == 95.41
    assert payload["source"] == "frankfurter"
    write_cached.assert_called_once()


def test_refresh_does_not_cache_fallback_on_http_error():
    with patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError(
            "network down"
        )
        with patch.object(fx_rates, "_write_cached") as write_cached:
            payload = fx_rates.refresh_usd_inr_rate()

    assert payload["rate"] == fx_rates._DEFAULT_RATE
    assert payload["source"] == "default"
    write_cached.assert_not_called()


def test_refresh_does_not_cache_fallback_on_bad_payload():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"date": "2026-08-15", "base": "USD", "quote": "INR"}

    with patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = response
        with patch.object(fx_rates, "_write_cached") as write_cached:
            payload = fx_rates.refresh_usd_inr_rate()

    assert payload["source"] == "default"
    write_cached.assert_not_called()


def test_read_cached_ignores_default_source():
    with patch.object(fx_rates, "_client") as redis_client:
        redis_client.return_value.get.return_value = (
            '{"rate": 83.0, "source": "default", "as_of": "2026-08-15T00:00:00+00:00"}'
        )
        assert fx_rates._read_cached() is None
