#!/usr/bin/env python3
"""Import the public OpenRouter chat model catalog into app/config/models.json."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_JSON = REPO_ROOT / "app" / "config" / "models.json"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

TOKEN_PER_MILLION = 1_000_000

PRICE_FIELD_MAP = {
    "prompt": "input_per_1m",
    "completion": "output_per_1m",
    "input_cache_read": "cache_read_per_1m",
    "input_cache_write": "cache_write_per_1m",
    "internal_reasoning": "reasoning_per_1m",
}

SKIP_ID_FRAGMENTS = (
    "embed",
    "embedding",
    "rerank",
    "moderation",
)

# Models published on OpenRouter but missing from GET /models (or pricing omitted).
MANUAL_OPENROUTER_MODELS: Dict[str, Dict[str, Any]] = {
    "typesafe/jev-1.13": {
        "provider": "openrouter",
        "model_type": "llm",
        "description": "Jev 1.13 evaluation model (TypeSafe) via OpenRouter",
        "openrouter_name": "Jev 1.13",
        "pricing": {
            "source": "openrouter_import",
            "usage_kind": "llm",
            "input_per_1m": 0.04,
            "output_per_1m": 0.0,
        },
    },
}


def apply_manual_openrouter_models(
    entries: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    merged = dict(entries)
    merged.update(MANUAL_OPENROUTER_MODELS)
    return merged


def _parse_non_negative_price(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount < 0:
        return None
    return round(amount * TOKEN_PER_MILLION, 8)


def pricing_from_openrouter(pricing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Map OpenRouter per-token USD strings to models.json plan pricing fields."""
    block: Dict[str, Any] = {
        "source": "openrouter_import",
        "usage_kind": "llm",
    }
    if not pricing:
        return block
    for src_key, dest_key in PRICE_FIELD_MAP.items():
        per_m = _parse_non_negative_price(pricing.get(src_key))
        if per_m is not None:
            block[dest_key] = per_m
    return block


def should_include_openrouter_model(model: Dict[str, Any]) -> bool:
    """Keep chat models whose output includes text."""
    model_id = str(model.get("id") or "").lower()
    if not model_id:
        return False
    if any(fragment in model_id for fragment in SKIP_ID_FRAGMENTS):
        return False

    architecture = model.get("architecture") or {}
    output_modalities = architecture.get("output_modalities") or []
    if not output_modalities:
        return False
    normalized = {str(m).lower() for m in output_modalities}
    if "text" not in normalized:
        return False
    if normalized == {"image"}:
        return False
    return True


def catalog_entry_from_openrouter_model(model: Dict[str, Any]) -> Dict[str, Any]:
    model_id = str(model["id"])
    name = str(model.get("name") or model_id).strip()
    description = str(model.get("description") or name).strip()
    entry: Dict[str, Any] = {
        "provider": "openrouter",
        "model_type": "llm",
        "description": description[:500] if description else name,
        "pricing": pricing_from_openrouter(model.get("pricing")),
    }
    if name and name != model_id:
        entry["openrouter_name"] = name
    return entry


def build_openrouter_catalog(models_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    entries: Dict[str, Dict[str, Any]] = {}
    for model in models_payload.get("data") or []:
        if not isinstance(model, dict):
            continue
        if not should_include_openrouter_model(model):
            continue
        model_id = str(model.get("id") or "").strip()
        if not model_id:
            continue
        entries[model_id] = catalog_entry_from_openrouter_model(model)
    return entries


def merge_openrouter_into_models(
    models: Dict[str, Any],
    openrouter_entries: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Drop prior openrouter rows and append the new catalog without clobbering other providers."""
    merged: Dict[str, Any] = {}
    for key, cfg in models.items():
        if key == "sample_spec":
            merged[key] = cfg
            continue
        if not isinstance(cfg, dict):
            merged[key] = cfg
            continue
        if cfg.get("provider") == "openrouter":
            continue
        merged[key] = cfg

    for model_id, entry in sorted(openrouter_entries.items()):
        existing = merged.get(model_id)
        if existing is not None and existing.get("provider") != "openrouter":
            continue
        merged[model_id] = entry
    return merged


def fetch_openrouter_models(url: str = OPENROUTER_MODELS_URL) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def sync_openrouter_models(
    *,
    models_path: Path = MODELS_JSON,
    url: str = OPENROUTER_MODELS_URL,
    dry_run: bool = False,
) -> int:
    payload = fetch_openrouter_models(url)
    openrouter_entries = apply_manual_openrouter_models(
        build_openrouter_catalog(payload)
    )
    models = json.loads(models_path.read_text(encoding="utf-8"))
    merged = merge_openrouter_into_models(models, openrouter_entries)
    if not dry_run:
        models_path.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return len(openrouter_entries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and merge in memory without writing models.json",
    )
    parser.add_argument(
        "--models-path",
        type=Path,
        default=MODELS_JSON,
        help="Path to models.json",
    )
    args = parser.parse_args()
    count = sync_openrouter_models(
        models_path=args.models_path,
        dry_run=args.dry_run,
    )
    action = "Would import" if args.dry_run else "Imported"
    print(f"{action} {count} OpenRouter LLM models into {args.models_path}")


if __name__ == "__main__":
    main()
