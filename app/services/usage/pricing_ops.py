"""Ops helpers for usage pricing catalog maintenance."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.usage.pricing import (
    DEFAULT_RATES_EFFECTIVE_FROM,
    _pricing_entries_from_models_json,
    _rates_table,
    seed_pricing_rates,
)
from app.services.usage.pricing_cache import invalidate_all_pricing_cache

_MODELS_JSON_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "models.json"
)
_CATALOG_JSON_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "pricing_catalog.json"
)

_RATE_COMPARE_COLUMNS = (
    "input_micro_usd_per_million",
    "output_micro_usd_per_million",
    "cache_read_micro_usd_per_million",
    "cache_creation_micro_usd_per_million",
    "reasoning_micro_usd_per_million",
    "audio_micro_usd_per_second",
    "tts_micro_usd_per_million_chars",
)


def models_missing_pricing_blocks() -> List[str]:
    if not _MODELS_JSON_PATH.exists():
        return []
    payload = json.loads(_MODELS_JSON_PATH.read_text(encoding="utf-8"))
    missing: List[str] = []
    for model_name, config in payload.items():
        if model_name.startswith("_") or not isinstance(config, dict):
            continue
        pricing = config.get("pricing")
        if not isinstance(pricing, dict):
            missing.append(model_name)
    return sorted(missing)


def litellm_unresolved_models() -> List[Dict[str, Any]]:
    if not _CATALOG_JSON_PATH.exists():
        return []
    payload = json.loads(_CATALOG_JSON_PATH.read_text(encoding="utf-8"))
    meta = payload.get("_metadata")
    if not isinstance(meta, dict):
        return []
    unresolved = meta.get("unresolved")
    return unresolved if isinstance(unresolved, list) else []


def _load_db_rates(
    db: Session, *, effective_from: date
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    table = _rates_table(db)
    rows = db.execute(
        text(
            f"""
            SELECT model, usage_kind, {_rate_columns_sql()}
            FROM {table}
            WHERE effective_from = CAST(:effective_from AS date)
            """
        ),
        {"effective_from": effective_from.isoformat()},
    ).mappings().all()
    return {(row["model"], row["usage_kind"]): dict(row) for row in rows}


def _rate_columns_sql() -> str:
    return ", ".join(_RATE_COMPARE_COLUMNS)


def diff_models_json_vs_db(
    db: Session, *, effective_from: Optional[date] = None
) -> Dict[str, Any]:
    day = effective_from or DEFAULT_RATES_EFFECTIVE_FROM
    json_rates = _pricing_entries_from_models_json()
    db_rates = _load_db_rates(db, effective_from=day)

    json_keys = {(model, entry.get("usage_kind") or "llm") for model, entry in json_rates.items()}
    db_keys = set(db_rates.keys())

    only_in_json = sorted(json_keys - db_keys)
    only_in_db = sorted(db_keys - json_keys)
    mismatches: List[Dict[str, Any]] = []

    for key in sorted(json_keys & db_keys):
        model, usage_kind = key
        expected = json_rates[model]
        actual = db_rates[key]
        field_diffs: Dict[str, Dict[str, int]] = {}
        for column in _RATE_COMPARE_COLUMNS:
            left = int(expected.get(column) or 0)
            right = int(actual.get(column) or 0)
            if left != right:
                field_diffs[column] = {"models_json": left, "database": right}
        if field_diffs:
            mismatches.append(
                {
                    "model": model,
                    "usage_kind": usage_kind,
                    "fields": field_diffs,
                }
            )

    return {
        "effective_from": day.isoformat(),
        "models_json_count": len(json_rates),
        "database_count": len(db_rates),
        "only_in_models_json": [
            {"model": model, "usage_kind": kind} for model, kind in only_in_json
        ],
        "only_in_database": [
            {"model": model, "usage_kind": kind} for model, kind in only_in_db
        ],
        "mismatches": mismatches,
        "missing_pricing_blocks": models_missing_pricing_blocks(),
        "litellm_unresolved": litellm_unresolved_models(),
        "in_sync": not only_in_json and not only_in_db and not mismatches,
    }


def seed_rates_from_models_json(
    db: Session, *, effective_from: Optional[date] = None
) -> int:
    return seed_pricing_rates(db, effective_from=effective_from)


def pricing_sync_on_startup_enabled() -> bool:
    from app.config import settings

    return bool(settings.USAGE_PRICING_SYNC_ON_STARTUP)


def _later_rate_starts(db: Session, *, effective_from: date) -> Dict[Tuple[str, str], date]:
    """Earliest rate dated after ``effective_from`` per (model, usage_kind)."""
    table = _rates_table(db)
    rows = db.execute(
        text(
            f"SELECT model, usage_kind, MIN(effective_from) FROM {table} "
            "WHERE effective_from > CAST(:day AS date) GROUP BY model, usage_kind"
        ),
        {"day": effective_from.isoformat()},
    ).all()
    return {(row[0], row[1]): row[2] for row in rows}


def sync_rates_from_models_json(
    db: Session, *, effective_from: Optional[date] = None
) -> Dict[str, List[str]]:
    """Upsert models.json baseline rates that are missing from or differ in the DB.

    Baseline rows (dated ``effective_from``) always follow models.json. A
    later-dated row for the same (model, usage_kind) still takes precedence from
    its own date at runtime, so those keys are reported as ``shadowed`` rather
    than implying usage is now billed at the models.json price. Rows that exist
    only in the database are left alone (usage history may reference them).
    Commits, then invalidates the pricing cache so workers see the new rates.
    """
    day = effective_from or DEFAULT_RATES_EFFECTIVE_FROM
    report = diff_models_json_vs_db(db, effective_from=day)
    new = {(item["model"], item["usage_kind"]) for item in report["only_in_models_json"]}
    changed = {(item["model"], item["usage_kind"]) for item in report["mismatches"]}
    synced = new | changed
    if not synced:
        return {"added": [], "updated": [], "shadowed": []}

    later = _later_rate_starts(db, effective_from=day)
    seed_pricing_rates(db, effective_from=day, models={model for model, _ in synced})
    db.commit()
    # seed_pricing_rates invalidates before commit; a worker may have cached
    # a stale rate in between, so invalidate again once the rows are visible.
    invalidate_all_pricing_cache()
    return {
        "added": sorted(model for model, _ in new),
        "updated": sorted(model for model, _ in changed),
        "shadowed": [
            f"{model} ({kind}) from {later[(model, kind)].isoformat()}"
            for model, kind in sorted(synced & later.keys())
        ],
    }
