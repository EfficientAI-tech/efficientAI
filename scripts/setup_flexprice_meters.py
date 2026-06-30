#!/usr/bin/env python3
"""Create Flexprice features and meters for EfficientAI usage metering catalog."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
from flexprice import Flexprice

from app.config import load_config_from_file, settings

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yml"

# (event_name, display_name, aggregation_type, aggregation_field|None)
METERS: list[tuple[str, str, str, str | None]] = [
    # Voice playground
    ("blind_test.share_created", "Blind Test Share Created", "COUNT", None),
    ("blind_test.response_submitted", "Blind Test Response Submitted", "COUNT", None),
    ("tts.generation_started", "TTS Generation Started", "COUNT", None),
    ("tts.sample_synthesized", "TTS Sample Synthesized", "SUM", "quantity"),
    ("tts.report_requested", "TTS Report Requested", "COUNT", None),
    ("tts.report_completed", "TTS Report Completed", "COUNT", None),
    # Call imports
    ("call_import.batch_created", "Call Import Batch Created", "SUM", "quantity"),
    ("call_import.evaluation_completed", "Call Import Evaluation Completed", "SUM", "quantity"),
    # Agent playground
    ("playground.web_call_started", "Playground Web Call Started", "COUNT", None),
    ("playground.websocket_session_started", "Playground Websocket Session Started", "COUNT", None),
    ("playground.call_evaluated", "Playground Call Evaluated", "COUNT", None),
    ("playground.evaluation_completed", "Playground Evaluation Completed", "COUNT", None),
    # Evaluators
    ("evaluator.run_requested", "Evaluator Run Requested", "SUM", "quantity"),
    ("evaluator.run_completed", "Evaluator Run Completed", "COUNT", None),
    # Legacy evaluations
    ("evaluation.created", "Evaluation Created", "COUNT", None),
    ("evaluation.completed", "Evaluation Completed", "COUNT", None),
    # Prompt optimization
    ("prompt_optimization.run_started", "Prompt Optimization Run Started", "COUNT", None),
    ("prompt_optimization.run_completed", "Prompt Optimization Run Completed", "COUNT", None),
    # Judge alignment
    ("judge_alignment.run_started", "Judge Alignment Run Started", "COUNT", None),
    ("judge_alignment.run_completed", "Judge Alignment Run Completed", "COUNT", None),
    # Observability
    ("observability.call_ingested", "Observability Call Ingested", "COUNT", None),
    ("observability.call_evaluated", "Observability Call Evaluated", "COUNT", None),
    # Test agents
    ("test_agent.conversation_started", "Test Agent Conversation Started", "COUNT", None),
    ("test_agent.conversation_ended", "Test Agent Conversation Ended", "SUM", "quantity"),
    # LLM assist
    ("metrics.llm_assist", "Metrics LLM Assist", "COUNT", None),
    ("chat.completion", "Chat Completion", "SUM", "quantity"),
]

LICENSE_FEATURES: list[dict[str, Any]] = [
    {
        "name": "Call Imports",
        "lookup_key": "call_imports",
        "description": "CSV/audio call import batches, row processing, and evaluations",
        "unit_singular": "batch",
        "unit_plural": "batches",
        "event_name": "call_import.batch_created",
        "aggregation": {"type": "COUNT"},
    },
    {
        "name": "Voice Playground",
        "lookup_key": "voice_playground",
        "description": "TTS comparisons, blind tests, and voice quality reports",
        "unit_singular": "share",
        "unit_plural": "shares",
        "event_name": "blind_test.share_created",
        "aggregation": {"type": "COUNT"},
    },
    {
        "name": "GEPA Optimization",
        "lookup_key": "gepa_optimization",
        "description": "Prompt optimization (GEPA) runs",
        "unit_singular": "run",
        "unit_plural": "runs",
        "event_name": "prompt_optimization.run_started",
        "aggregation": {"type": "COUNT"},
    },
]


def _headers() -> dict[str, str]:
    return {"x-api-key": settings.FLEXPRICE_API_KEY or "", "Content-Type": "application/json"}


def _base_url() -> str:
    return (settings.FLEXPRICE_API_HOST or "").rstrip("/")


def _meter_payload(name: str, event_name: str, agg_type: str, field: str | None) -> dict[str, Any]:
    aggregation: dict[str, str] = {"type": agg_type}
    if field and agg_type in {"SUM", "MAX", "LATEST", "COUNT_UNIQUE", "AVG"}:
        aggregation["field"] = field
    return {
        "name": name,
        "event_name": event_name,
        "aggregation": aggregation,
        "reset_usage": "BILLING_PERIOD",
    }


def _list_meters(client: httpx.Client) -> dict[str, dict]:
    existing: dict[str, dict] = {}
    offset = 0
    while True:
        resp = client.get(
            f"{_base_url()}/meters",
            headers=_headers(),
            params={"limit": 200, "offset": offset},
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items") or []
        for item in items:
            event_name = item.get("event_name")
            if event_name:
                existing[event_name] = item
        pagination = data.get("pagination") or {}
        total = pagination.get("total")
        offset += len(items)
        if not items or (total is not None and offset >= total):
            break
    return existing


def _create_meter(client: httpx.Client, event_name: str, name: str, agg_type: str, field: str | None) -> dict:
    payload = _meter_payload(name, event_name, agg_type, field)
    resp = client.post(f"{_base_url()}/meters", headers=_headers(), json=payload)
    if resp.status_code == 409 or (
        resp.status_code == 400 and "exist" in resp.text.lower()
    ):
        return {"skipped": True, "event_name": event_name, "detail": resp.text}
    resp.raise_for_status()
    return resp.json()


def _list_feature_lookup_keys(sdk: Flexprice) -> set[str]:
    keys: set[str] = set()
    offset = 0
    while True:
        resp = sdk.features.query_feature(limit=200, offset=offset)
        items = resp.items or []
        for item in items:
            if item.lookup_key:
                keys.add(item.lookup_key)
        offset += len(items)
        if not items:
            break
    return keys


def _create_license_feature(sdk: Flexprice, spec: dict[str, Any]) -> dict:
    meter = {
        "name": spec["name"],
        "event_name": spec["event_name"],
        "aggregation": spec["aggregation"],
        "reset_usage": "BILLING_PERIOD",
    }
    try:
        result = sdk.features.create_feature(
            name=spec["name"],
            type_="metered",
            lookup_key=spec["lookup_key"],
            description=spec["description"],
            unit_singular=spec.get("unit_singular"),
            unit_plural=spec.get("unit_plural"),
            meter=meter,
        )
        return {"created": True, "lookup_key": spec["lookup_key"], "id": result.id}
    except Exception as exc:
        message = str(exc).lower()
        if "already exist" in message or "duplicate" in message:
            return {"skipped": True, "lookup_key": spec["lookup_key"], "detail": str(exc)}
        raise


def main() -> int:
    if CONFIG_PATH.exists():
        load_config_from_file(str(CONFIG_PATH))

    if not settings.FLEXPRICE_ENABLED or not settings.FLEXPRICE_API_KEY:
        print("Flexprice is not enabled or FLEXPRICE_API_KEY is missing.", file=sys.stderr)
        return 1

    created_meters: list[str] = []
    skipped_meters: list[str] = []
    failed_meters: list[str] = []
    created_features: list[str] = []
    skipped_features: list[str] = []
    failed_features: list[str] = []

    with httpx.Client(timeout=60.0) as http_client:
        existing_meters = _list_meters(http_client)
        for event_name, name, agg_type, field in METERS:
            if event_name in existing_meters:
                skipped_meters.append(event_name)
                continue
            try:
                result = _create_meter(http_client, event_name, name, agg_type, field)
                if result.get("skipped"):
                    skipped_meters.append(event_name)
                else:
                    created_meters.append(event_name)
            except Exception as exc:
                failed_meters.append(f"{event_name}: {exc}")

    with Flexprice(
        server_url=settings.FLEXPRICE_API_HOST,
        api_key_auth=settings.FLEXPRICE_API_KEY,
    ) as sdk:
        existing_feature_keys = _list_feature_lookup_keys(sdk)
        for spec in LICENSE_FEATURES:
            key = spec["lookup_key"]
            if key in existing_feature_keys:
                skipped_features.append(key)
                continue
            try:
                result = _create_license_feature(sdk, spec)
                if result.get("skipped"):
                    skipped_features.append(key)
                else:
                    created_features.append(key)
            except Exception as exc:
                failed_features.append(f"{key}: {exc}")

    summary = {
        "meters": {"created": created_meters, "skipped": skipped_meters, "failed": failed_meters},
        "features": {"created": created_features, "skipped": skipped_features, "failed": failed_features},
    }
    print(json.dumps(summary, indent=2))
    return 1 if (failed_meters or failed_features) else 0


if __name__ == "__main__":
    raise SystemExit(main())
