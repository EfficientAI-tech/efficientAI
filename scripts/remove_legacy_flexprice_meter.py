#!/usr/bin/env python3
"""Remove legacy Flexprice meters/features superseded by the metering catalog."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
from flexprice import Flexprice

from app.config import load_config_from_file, settings

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yml"

LEGACY_EVENT_NAMES = {
    "BLIND_TEST_SHARE_CREATED_EVENT",
}


def _headers() -> dict[str, str]:
    return {"x-api-key": settings.FLEXPRICE_API_KEY or ""}


def _base_url() -> str:
    return (settings.FLEXPRICE_API_HOST or "").rstrip("/")


def _delete_meter(client: httpx.Client, meter_id: str) -> dict:
    for method, suffix in (("DELETE", ""), ("POST", "/archive")):
        url = f"{_base_url()}/meters/{meter_id}{suffix}"
        if method == "DELETE":
            resp = client.delete(url, headers=_headers())
        else:
            resp = client.post(url, headers=_headers())
        if resp.status_code in (200, 204, 404):
            return {"meter_id": meter_id, "method": method, "status": resp.status_code}
    resp.raise_for_status()
    return {"meter_id": meter_id, "status": resp.status_code}


def main() -> int:
    if CONFIG_PATH.exists():
        load_config_from_file(str(CONFIG_PATH))

    if not settings.FLEXPRICE_API_KEY:
        print("FLEXPRICE_API_KEY is missing.", file=sys.stderr)
        return 1

    results: dict[str, list] = {"meters_removed": [], "features_removed": [], "errors": []}

    with httpx.Client(timeout=60.0) as client:
        resp = client.get(f"{_base_url()}/meters", headers=_headers(), params={"limit": 200})
        resp.raise_for_status()
        for meter in resp.json().get("items") or []:
            event_name = meter.get("event_name") or ""
            if event_name not in LEGACY_EVENT_NAMES:
                continue
            try:
                results["meters_removed"].append(
                    {"event_name": event_name, **_delete_meter(client, meter["id"])}
                )
            except Exception as exc:
                results["errors"].append(f"meter {event_name}: {exc}")

    with Flexprice(
        server_url=settings.FLEXPRICE_API_HOST,
        api_key_auth=settings.FLEXPRICE_API_KEY,
    ) as sdk:
        resp = sdk.features.query_feature(limit=200)
        for item in resp.items or []:
            lookup = (item.lookup_key or "").lower()
            name = (item.name or "").upper()
            meter = item.meter
            meter_event = (meter.event_name if meter else "") or ""
            if (
                meter_event in LEGACY_EVENT_NAMES
                or lookup == "feat-blind_test_share_created_event"
                or name in LEGACY_EVENT_NAMES
            ):
                try:
                    sdk.features.delete_feature(id=item.id)
                    results["features_removed"].append(
                        {"id": item.id, "lookup_key": item.lookup_key, "name": item.name}
                    )
                except Exception as exc:
                    results["errors"].append(f"feature {item.lookup_key or item.name}: {exc}")

    print(json.dumps(results, indent=2))
    return 1 if results["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
