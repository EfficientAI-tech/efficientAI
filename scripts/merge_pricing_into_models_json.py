#!/usr/bin/env python3
"""Merge pricing_catalog.json micro-USD rates into models.json plan-format pricing blocks."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_JSON = REPO_ROOT / "app" / "config" / "models.json"
CATALOG_JSON = REPO_ROOT / "app" / "config" / "pricing_catalog.json"
MANUAL_JSON = REPO_ROOT / "app" / "config" / "pricing_manual.json"
MICRO = 1_000_000


def _usd_per_m(micro: int) -> float:
    return round(micro / MICRO, 8)


def _micro_entry_to_plan_pricing(entry: dict) -> dict:
    usage_kind = entry.get("usage_kind") or "llm"
    source = entry.get("_price_source") or (
        "litellm_import" if entry.get("_litellm_key") else "catalog"
    )
    pricing: dict = {"source": source}
    if usage_kind:
        pricing["usage_kind"] = usage_kind

    if entry.get("input_micro_usd_per_million"):
        pricing["input_per_1m"] = _usd_per_m(entry["input_micro_usd_per_million"])
    if entry.get("output_micro_usd_per_million"):
        pricing["output_per_1m"] = _usd_per_m(entry["output_micro_usd_per_million"])
    if entry.get("cache_read_micro_usd_per_million"):
        pricing["cache_read_per_1m"] = _usd_per_m(
            entry["cache_read_micro_usd_per_million"]
        )
    if entry.get("cache_creation_micro_usd_per_million"):
        pricing["cache_write_per_1m"] = _usd_per_m(
            entry["cache_creation_micro_usd_per_million"]
        )
    if entry.get("reasoning_micro_usd_per_million"):
        pricing["reasoning_per_1m"] = _usd_per_m(
            entry["reasoning_micro_usd_per_million"]
        )
    if entry.get("audio_micro_usd_per_second"):
        pricing["audio_per_minute"] = round(
            entry["audio_micro_usd_per_second"] * 60 / MICRO, 8
        )
    if entry.get("tts_micro_usd_per_million_chars"):
        pricing["tts_per_1m_characters"] = _usd_per_m(
            entry["tts_micro_usd_per_million_chars"]
        )
    return pricing


def _load_catalog() -> dict:
    merged: dict = {}
    if CATALOG_JSON.exists():
        payload = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
        merged.update(
            {
                k: v
                for k, v in payload.items()
                if not k.startswith("_") and isinstance(v, dict)
            }
        )
    if MANUAL_JSON.exists():
        payload = json.loads(MANUAL_JSON.read_text(encoding="utf-8"))
        for key, value in payload.items():
            if not key.startswith("_") and isinstance(value, dict):
                merged[key] = value
    return merged


def merge() -> tuple[int, int]:
    models = json.loads(MODELS_JSON.read_text(encoding="utf-8"))
    catalog = _load_catalog()
    updated = 0
    skipped = 0
    for model_name, cfg in models.items():
        if model_name.startswith("_") or not isinstance(cfg, dict):
            continue
        entry = catalog.get(model_name)
        if not entry:
            skipped += 1
            continue
        pricing = _micro_entry_to_plan_pricing(entry)
        if len(pricing) <= 1:
            skipped += 1
            continue
        cfg["pricing"] = pricing
        updated += 1
    MODELS_JSON.write_text(
        json.dumps(models, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return updated, skipped


def main() -> int:
    updated, skipped = merge()
    print(f"merged pricing into {updated} model(s); skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
