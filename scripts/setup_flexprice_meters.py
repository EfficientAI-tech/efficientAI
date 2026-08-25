#!/usr/bin/env python3
"""Create Flexprice features and meters for EfficientAI usage metering catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from flexprice import Flexprice

from app.config import load_config_from_file, settings

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yml"

CALL_IMPORT_BATCH_EVENT = "call_import.batch_created"
CALL_IMPORT_BATCH_METER_NAME = "Call Imports"
CALL_IMPORT_BATCH_AGG_TYPE = "SUM"
CALL_IMPORT_BATCH_AGG_FIELD = "quantity"
AGENT_PLAYGROUND_PRIMARY_EVENT = "playground.web_call_started"
EVALUATOR_RUN_REQUESTED_EVENT = "evaluator.run_requested"
JUDGE_ALIGNMENT_PRIMARY_EVENT = "judge_alignment.run_completed"
METRICS_AI_ASSIST_EVENT = "metrics.ai_assist"
METRIC_STUDIO_PRIMARY_EVENT = "metric_studio.run_completed"
SCENARIO_AI_TEXT_EVENT = "scenario.ai_text_generated"

# (event_name, display_name, aggregation_type, aggregation_field|None)
METERS: list[tuple[str, str, str, str | None]] = [
    # Voice playground
    ("blind_test.share_created", "Blind Test Share Created", "COUNT", None),
    ("blind_test.response_submitted", "Blind Test Response Submitted", "COUNT", None),
    ("tts.generation_started", "TTS Generation Started", "COUNT", None),
    ("tts.sample_synthesized", "TTS Sample Synthesized", "SUM", "quantity"),
    ("tts.report_requested", "TTS Report Requested", "COUNT", None),
    ("tts.report_completed", "TTS Report Completed", "COUNT", None),
    # Call imports (batch_created meter comes from the call_imports license feature)
    ("call_import.evaluation_started", "Call Import Evaluation Started", "COUNT", None),
    ("call_import.evaluation_completed", "Call Import Evaluation Completed", "SUM", "quantity"),
    (
        "call_import.recording_minutes_billed",
        "Call Import Recording Minutes",
        "SUM",
        "billable_minutes",
    ),
    ("call_import.pdf_report_generated", "Call Import PDF Report Generated", "COUNT", None),
    # Agent playground (web_call_started meter comes from the agent_playground license feature)
    ("playground.websocket_session_started", "Playground Websocket Session Started", "COUNT", None),
    ("playground.call_evaluated", "Playground Call Evaluated", "COUNT", None),
    ("playground.evaluation_completed", "Playground Evaluation Completed", "COUNT", None),
    # Evaluators (run_requested meter comes from the evaluators license feature)
    ("evaluator.run_completed", "Evaluator Run Completed", "COUNT", None),
    # Legacy evaluations
    ("evaluation.created", "Evaluation Created", "COUNT", None),
    ("evaluation.completed", "Evaluation Completed", "COUNT", None),
    # Prompt optimization
    ("prompt_optimization.run_started", "Prompt Optimization Run Started", "COUNT", None),
    ("prompt_optimization.run_completed", "Prompt Optimization Run Completed", "COUNT", None),
    # Judge alignment (run_completed meter comes from the judge_alignment license feature)
    ("judge_alignment.run_started", "Judge Alignment Run Started", "COUNT", None),
    # Observability
    ("observability.call_ingested", "Observability Call Ingested", "COUNT", None),
    ("observability.call_evaluated", "Observability Call Evaluated", "COUNT", None),
    # Test agents
    ("test_agent.conversation_started", "Test Agent Conversation Started", "COUNT", None),
    ("test_agent.conversation_ended", "Test Agent Conversation Ended", "COUNT", None),
    # Metric studio (run_completed meter comes from the metric_studio license feature)
    ("metric_studio.item_evaluated", "Metric Studio Item Evaluated", "COUNT", None),
    # Metrics AI assist (primary meter comes from the metrics_ai_assist license feature)
    # Scenario AI text (primary meter comes from the scenario_ai license feature)
]

LICENSE_FEATURES: list[dict[str, Any]] = [
    {
        "name": "Call Imports",
        "lookup_key": "call_imports",
        "description": "CSV/audio call import batches, row processing, and evaluations",
        "unit_singular": "row",
        "unit_plural": "rows",
        "event_name": CALL_IMPORT_BATCH_EVENT,
        "aggregation": {"type": CALL_IMPORT_BATCH_AGG_TYPE, "field": CALL_IMPORT_BATCH_AGG_FIELD},
    },
    {
        "name": "Agent Playground",
        "lookup_key": "agent_playground",
        "description": "Agent web calls, websocket sessions, evaluations, and test-agent conversations",
        "unit_singular": "session",
        "unit_plural": "sessions",
        "event_name": AGENT_PLAYGROUND_PRIMARY_EVENT,
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
    {
        "name": "Evaluators",
        "lookup_key": "evaluators",
        "description": "Batch evaluator simulation runs and completions",
        "unit_singular": "run",
        "unit_plural": "runs",
        "event_name": EVALUATOR_RUN_REQUESTED_EVENT,
        "aggregation": {"type": "SUM", "field": "quantity"},
    },
    {
        "name": "Judge Alignment",
        "lookup_key": "judge_alignment",
        "description": "Judge calibration runs on labeled datasets",
        "unit_singular": "run",
        "unit_plural": "runs",
        "event_name": JUDGE_ALIGNMENT_PRIMARY_EVENT,
        "aggregation": {"type": "COUNT"},
    },
    {
        "name": "Metrics AI Assist",
        "lookup_key": "metrics_ai_assist",
        "description": "AI-assisted metric creation and bulk label parsing in Metrics Management",
        "unit_singular": "request",
        "unit_plural": "requests",
        "event_name": METRICS_AI_ASSIST_EVENT,
        "aggregation": {"type": "COUNT"},
    },
    {
        "name": "Metric Studio",
        "lookup_key": "metric_studio",
        "description": "Batch metric scoring runs in Metrics Studio",
        "unit_singular": "run",
        "unit_plural": "runs",
        "event_name": METRIC_STUDIO_PRIMARY_EVENT,
        "aggregation": {"type": "COUNT"},
    },
    {
        "name": "Scenario AI Text",
        "lookup_key": "scenario_ai",
        "description": "AI-generated text for scenarios and similar assistant flows",
        "unit_singular": "generation",
        "unit_plural": "generations",
        "event_name": SCENARIO_AI_TEXT_EVENT,
        "aggregation": {"type": "COUNT"},
    },
]

FEATURE_OWNED_EVENT_NAMES = frozenset(spec["event_name"] for spec in LICENSE_FEATURES)


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


def meter_aggregation_matches(
    meter: dict[str, Any],
    *,
    agg_type: str,
    agg_field: str | None = None,
) -> bool:
    aggregation = meter.get("aggregation") or {}
    if (aggregation.get("type") or "").upper() != agg_type.upper():
        return False
    if agg_field is None:
        return not aggregation.get("field")
    return (aggregation.get("field") or "") == agg_field


def _is_active_meter(meter: dict[str, Any]) -> bool:
    return (meter.get("status") or "published").lower() == "published"


def _list_all_meters(client: httpx.Client, *, active_only: bool = False) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        resp = client.get(
            f"{_base_url()}/meters",
            headers=_headers(),
            params={"limit": 200, "offset": offset},
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("items") or []
        if active_only:
            batch = [meter for meter in batch if _is_active_meter(meter)]
        items.extend(batch)
        pagination = data.get("pagination") or {}
        total = pagination.get("total")
        offset += len(data.get("items") or [])
        if not data.get("items") or (total is not None and offset >= total):
            break
    return items


def _list_meters_by_event(client: httpx.Client, *, active_only: bool = False) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for meter in _list_all_meters(client, active_only=active_only):
        event_name = meter.get("event_name")
        if not event_name:
            continue
        grouped.setdefault(event_name, []).append(meter)
    return grouped


def _create_meter(client: httpx.Client, event_name: str, name: str, agg_type: str, field: str | None) -> dict:
    payload = _meter_payload(name, event_name, agg_type, field)
    resp = client.post(f"{_base_url()}/meters", headers=_headers(), json=payload)
    if resp.status_code == 409 or (
        resp.status_code == 400 and "exist" in resp.text.lower()
    ):
        return {"skipped": True, "event_name": event_name, "detail": resp.text}
    resp.raise_for_status()
    return resp.json()


def _delete_meter(client: httpx.Client, meter_id: str) -> None:
    resp = client.delete(f"{_base_url()}/meters/{meter_id}", headers=_headers())
    resp.raise_for_status()


def _list_prices(client: httpx.Client) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        resp = client.get(
            f"{_base_url()}/prices",
            headers=_headers(),
            params={"limit": 200, "offset": offset},
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("items") or []
        items.extend(batch)
        pagination = data.get("pagination") or {}
        total = pagination.get("total")
        offset += len(batch)
        if not batch or (total is not None and offset >= total):
            break
    return items


def _active_prices_for_meter(prices: list[dict[str, Any]], meter_id: str) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for price in prices:
        if price.get("meter_id") != meter_id:
            continue
        if price.get("end_date"):
            continue
        if (price.get("status") or "").lower() in {"deleted", "archived", "disabled"}:
            continue
        active.append(price)
    return active


def _create_usage_price_from_template(
    client: httpx.Client,
    *,
    template: dict[str, Any],
    meter_id: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "entity_type": template.get("entity_type"),
        "entity_id": template.get("entity_id"),
        "type": template.get("type", "USAGE"),
        "billing_model": template.get("billing_model", "FLAT_FEE"),
        "billing_period": template.get("billing_period", "MONTHLY"),
        "billing_period_count": template.get("billing_period_count", 1),
        "billing_cadence": template.get("billing_cadence", "RECURRING"),
        "currency": template.get("currency", "usd"),
        "invoice_cadence": template.get("invoice_cadence", "ARREAR"),
        "price_unit_type": template.get("price_unit_type", "FIAT"),
        "meter_id": meter_id,
        "amount": template.get("amount", "1"),
        "display_name": template.get("display_name") or CALL_IMPORT_BATCH_METER_NAME,
    }
    if template.get("description"):
        payload["description"] = template["description"]
    if template.get("lookup_key"):
        payload["lookup_key"] = template["lookup_key"]
    if template.get("transform_quantity"):
        payload["transform_quantity"] = template["transform_quantity"]
    resp = client.post(f"{_base_url()}/prices", headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


def _terminate_price(client: httpx.Client, price_id: str) -> None:
    resp = client.request("DELETE", f"{_base_url()}/prices/{price_id}", headers=_headers(), json={})
    if resp.status_code == 404:
        return
    resp.raise_for_status()


def _dedupe_canonical_prices(
    client: httpx.Client,
    *,
    canonical_meter_id: str,
    prices: list[dict[str, Any]],
    result: dict[str, Any],
) -> None:
    active = _active_prices_for_meter(prices, canonical_meter_id)
    if len(active) <= 1:
        return
    active.sort(key=lambda price: price.get("created_at") or "", reverse=True)
    for duplicate in active[1:]:
        _terminate_price(client, duplicate["id"])
        result["terminated_prices"].append(duplicate["id"])
        result["subscription_resync_required"] = True


def _terminate_orphaned_batch_prices(
    client: httpx.Client,
    *,
    prices: list[dict[str, Any]],
    active_batch_meter_ids: set[str],
    result: dict[str, Any],
) -> None:
    batch_meter_ids = {
        meter["id"]
        for meter in _list_all_meters(client)
        if meter.get("event_name") == CALL_IMPORT_BATCH_EVENT
    }
    for price in prices:
        meter_id = price.get("meter_id")
        if not meter_id or meter_id not in batch_meter_ids:
            continue
        if meter_id in active_batch_meter_ids:
            continue
        if price.get("end_date"):
            continue
        if (price.get("status") or "").lower() in {"deleted", "archived", "disabled"}:
            continue
        _terminate_price(client, price["id"])
        result["terminated_prices"].append(price["id"])
        result["subscription_resync_required"] = True


PLAN_USAGE_RESTORE_NAMES = ("Voice Playground", "Blind Test")
# Fallback archived template price IDs when /prices list omits terminated prices.
PLAN_USAGE_ARCHIVE_TEMPLATE_IDS: dict[str, str] = {
    "Voice Playground": "price_01KVT8P9T8E52KHB1CA6HCVPV0",
    "Blind Test": "price_01KW9E4W02NND35R6W87Y7863K",
}


def _fetch_price(client: httpx.Client, price_id: str) -> dict[str, Any] | None:
    resp = client.get(f"{_base_url()}/prices/{price_id}", headers=_headers())
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def restore_missing_plan_usage_prices(client: httpx.Client) -> dict[str, Any]:
    """Recreate plan usage prices that were terminated but still have archived templates."""
    result: dict[str, Any] = {"restored": [], "skipped": []}
    all_prices = _list_prices(client)
    active_names = {
        price.get("display_name")
        for price in all_prices
        if price.get("entity_type") == "PLAN"
        and price.get("type") == "USAGE"
        and not price.get("end_date")
        and (price.get("status") or "published").lower() == "published"
    }

    for display_name in PLAN_USAGE_RESTORE_NAMES:
        if display_name in active_names:
            result["skipped"].append(display_name)
            continue
        templates = [
            price
            for price in all_prices
            if price.get("display_name") == display_name
            and price.get("entity_type") == "PLAN"
            and price.get("type") == "USAGE"
            and price.get("end_date")
        ]
        template: dict[str, Any] | None = None
        if templates:
            templates.sort(key=lambda price: price.get("end_date") or "", reverse=True)
            template = templates[0]
        else:
            archive_id = PLAN_USAGE_ARCHIVE_TEMPLATE_IDS.get(display_name)
            if archive_id:
                template = _fetch_price(client, archive_id)
        if not template:
            result["skipped"].append(display_name)
            continue
        restored = _create_usage_price_from_template(
            client,
            template=template,
            meter_id=template["meter_id"],
        )
        result["restored"].append({"display_name": display_name, "price_id": restored.get("id")})
    return result


def repair_call_import_batch_meter(client: httpx.Client) -> dict[str, Any]:
    """Ensure one SUM(quantity) meter for call_import.batch_created and remove duplicates."""
    result: dict[str, Any] = {
        "deleted_duplicate_meters": [],
        "deleted_legacy_meters": [],
        "terminated_prices": [],
        "created_meter_id": None,
        "created_price_ids": [],
        "kept_meter_id": None,
        "subscription_resync_required": False,
    }

    all_prices = _list_prices(client)
    batch_meters = _list_meters_by_event(client, active_only=True).get(CALL_IMPORT_BATCH_EVENT, [])

    correct_meters = [
        meter
        for meter in batch_meters
        if meter_aggregation_matches(
            meter,
            agg_type=CALL_IMPORT_BATCH_AGG_TYPE,
            agg_field=CALL_IMPORT_BATCH_AGG_FIELD,
        )
    ]
    incorrect_meters = [meter for meter in batch_meters if meter not in correct_meters]

    canonical_meter: dict[str, Any] | None = None
    if correct_meters:
        priced_correct = [
            meter
            for meter in correct_meters
            if _active_prices_for_meter(all_prices, meter["id"])
        ]
        canonical_meter = priced_correct[0] if priced_correct else correct_meters[0]
        result["kept_meter_id"] = canonical_meter["id"]

    prices_to_recreate: list[dict[str, Any]] = []
    for meter in incorrect_meters:
        meter_id = meter["id"]
        attached_prices = _active_prices_for_meter(all_prices, meter_id)
        if attached_prices:
            prices_to_recreate.extend(attached_prices)
        else:
            _delete_meter(client, meter_id)
            result["deleted_duplicate_meters"].append(
                {"id": meter_id, "name": meter.get("name")}
            )

    if canonical_meter is None or prices_to_recreate:
        if canonical_meter is None:
            canonical_meter = _create_meter(
                client,
                CALL_IMPORT_BATCH_EVENT,
                CALL_IMPORT_BATCH_METER_NAME,
                CALL_IMPORT_BATCH_AGG_TYPE,
                CALL_IMPORT_BATCH_AGG_FIELD,
            )
            result["created_meter_id"] = canonical_meter.get("id")
        result["kept_meter_id"] = canonical_meter["id"]

        existing_canonical_prices = _active_prices_for_meter(all_prices, canonical_meter["id"])
        for old_price in prices_to_recreate:
            if existing_canonical_prices:
                _terminate_price(client, old_price["id"])
                result["terminated_prices"].append(old_price["id"])
                result["subscription_resync_required"] = True
                continue
            new_price = _create_usage_price_from_template(
                client,
                template=old_price,
                meter_id=canonical_meter["id"],
            )
            result["created_price_ids"].append(new_price.get("id"))
            existing_canonical_prices = [new_price]
            _terminate_price(client, old_price["id"])
            result["terminated_prices"].append(old_price["id"])
            result["subscription_resync_required"] = True

        for meter in incorrect_meters:
            meter_id = meter["id"]
            if meter_id == canonical_meter["id"]:
                continue
            _delete_meter(client, meter_id)
            result["deleted_legacy_meters"].append(
                {"id": meter_id, "name": meter.get("name")}
            )

    extra_correct = [
        meter
        for meter in correct_meters
        if canonical_meter and meter["id"] != canonical_meter["id"]
    ]
    for meter in extra_correct:
        meter_id = meter["id"]
        attached_prices = _active_prices_for_meter(all_prices, meter_id)
        if attached_prices:
            continue
        _delete_meter(client, meter_id)
        result["deleted_duplicate_meters"].append(
            {"id": meter_id, "name": meter.get("name")}
        )

    if canonical_meter:
        refreshed_prices = _list_prices(client)
        active_batch_meter_ids = {
            meter["id"]
            for meter in _list_meters_by_event(client, active_only=True).get(CALL_IMPORT_BATCH_EVENT, [])
            if meter_aggregation_matches(
                meter,
                agg_type=CALL_IMPORT_BATCH_AGG_TYPE,
                agg_field=CALL_IMPORT_BATCH_AGG_FIELD,
            )
        }
        _terminate_orphaned_batch_prices(
            client,
            prices=refreshed_prices,
            active_batch_meter_ids=active_batch_meter_ids,
            result=result,
        )
        refreshed_prices = _list_prices(client)
        _dedupe_canonical_prices(
            client,
            canonical_meter_id=canonical_meter["id"],
            prices=refreshed_prices,
            result=result,
        )

    return result


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


def bootstrap_catalog() -> dict[str, Any]:
    created_meters: list[str] = []
    skipped_meters: list[str] = []
    failed_meters: list[str] = []
    created_features: list[str] = []
    skipped_features: list[str] = []
    failed_features: list[str] = []

    with httpx.Client(timeout=60.0) as http_client:
        existing_by_event = _list_meters_by_event(http_client)
        for event_name, name, agg_type, field in METERS:
            if event_name in FEATURE_OWNED_EVENT_NAMES:
                skipped_meters.append(event_name)
                continue
            if event_name in existing_by_event:
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

    return {
        "meters": {"created": created_meters, "skipped": skipped_meters, "failed": failed_meters},
        "features": {"created": created_features, "skipped": skipped_features, "failed": failed_features},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap or repair Flexprice metering catalog.")
    parser.add_argument(
        "--repair-call-imports",
        action="store_true",
        help="Remove duplicate batch_created meters and migrate pricing to SUM(quantity).",
    )
    parser.add_argument(
        "--restore-plan-usage-prices",
        action="store_true",
        help="Recreate missing Voice Playground and Blind Test plan usage prices from archived templates.",
    )
    args = parser.parse_args()

    if CONFIG_PATH.exists():
        load_config_from_file(str(CONFIG_PATH))

    if not settings.FLEXPRICE_ENABLED or not settings.FLEXPRICE_API_KEY:
        print("Flexprice is not enabled or FLEXPRICE_API_KEY is missing.", file=sys.stderr)
        return 1

    summary: dict[str, Any] = {}
    with httpx.Client(timeout=60.0) as http_client:
        if args.repair_call_imports:
            summary["call_import_batch_repair"] = repair_call_import_batch_meter(http_client)
        if args.restore_plan_usage_prices:
            summary["plan_usage_restore"] = restore_missing_plan_usage_prices(http_client)

    bootstrap_summary = bootstrap_catalog()
    summary.update(bootstrap_summary)

    print(json.dumps(summary, indent=2))

    repair = summary.get("call_import_batch_repair") or {}
    if repair.get("subscription_resync_required"):
        print(
            "\nNOTE: Plan prices were recreated. In Flexprice, open the plan and click "
            "'Sync Usage Charges', then refresh the customer subscription so line items "
            "reference the new price IDs.",
            file=sys.stderr,
        )

    failed_meters = bootstrap_summary["meters"]["failed"]
    failed_features = bootstrap_summary["features"]["failed"]
    return 1 if (failed_meters or failed_features) else 0


if __name__ == "__main__":
    raise SystemExit(main())
