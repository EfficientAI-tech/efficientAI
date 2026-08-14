"""Usage pricing: rate resolution, cost computation, seed, and rollup backfill."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.usage.pricing_cache import (
    get_cached_rate_payload,
    pricing_cache_key,
    set_cached_rate_payload,
)

DEFAULT_RATES_EFFECTIVE_FROM = date(2020, 1, 1)
# Back-compat alias for older migrations.
DEFAULT_CATALOG_EFFECTIVE_FROM = DEFAULT_RATES_EFFECTIVE_FROM

USAGE_KIND_LLM = "llm"
USAGE_KIND_STT = "stt"
USAGE_KIND_TTS = "tts"

MICRO_USD_PER_UNIT = 1_000_000
RATE_SOURCE_CATALOG = "catalog"
RATE_SOURCE_OVERRIDE = "override"

_MODELS_JSON_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "models.json"
)

_RATES_TABLE = "model_pricing_rates"
_RATES_TABLE_CACHE: Optional[str] = None


def _rates_table(db: Session) -> str:
    global _RATES_TABLE_CACHE
    if _RATES_TABLE_CACHE:
        return _RATES_TABLE_CACHE
    row = db.execute(text("SELECT to_regclass('public.model_pricing_rates')")).scalar()
    if row:
        _RATES_TABLE_CACHE = "model_pricing_rates"
        return _RATES_TABLE_CACHE
    row = db.execute(text("SELECT to_regclass('public.model_pricing_catalog')")).scalar()
    if row:
        _RATES_TABLE_CACHE = "model_pricing_catalog"
        return _RATES_TABLE_CACHE
    _RATES_TABLE_CACHE = _RATES_TABLE
    return _RATES_TABLE_CACHE


@dataclass(frozen=True)
class RateCard:
    source: str
    rate_id: UUID
    input_micro_usd_per_million: int = 0
    output_micro_usd_per_million: int = 0
    cache_read_micro_usd_per_million: int = 0
    cache_creation_micro_usd_per_million: int = 0
    reasoning_micro_usd_per_million: int = 0
    audio_micro_usd_per_second: int = 0
    tts_micro_usd_per_million_chars: int = 0


@dataclass(frozen=True)
class CostBreakdown:
    input_cost_micro_usd: int = 0
    output_cost_micro_usd: int = 0
    cache_read_cost_micro_usd: int = 0
    cache_creation_cost_micro_usd: int = 0
    reasoning_cost_micro_usd: int = 0
    audio_cost_micro_usd: int = 0
    tts_cost_micro_usd: int = 0
    total_cost_micro_usd: int = 0
    pricing_rate_source: Optional[str] = None
    pricing_rate_id: Optional[UUID] = None


@dataclass(frozen=True)
class UsageMetrics:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0
    audio_seconds: int = 0
    tts_characters: int = 0


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _normalize_rate_source(value: Any) -> str:
    source = str(value or "catalog").strip() or "catalog"
    if len(source) > 255:
        return source[:255]
    return source


def _usage_kind_for_model_type(model_type: Optional[str]) -> str:
    if model_type == "stt":
        return USAGE_KIND_STT
    if model_type in {"tts", "sts", "sound_effects", "music"}:
        return USAGE_KIND_TTS
    return USAGE_KIND_LLM


def _usd_per_million_to_micro(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(round(float(value) * MICRO_USD_PER_UNIT))
    except (TypeError, ValueError):
        return 0


def _usd_per_minute_to_micro_per_second(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(round(float(value) * MICRO_USD_PER_UNIT / 60.0))
    except (TypeError, ValueError):
        return 0


def _normalize_pricing_block(
    pricing: Dict[str, Any], *, model_type: Optional[str]
) -> Dict[str, Any]:
    """Convert models.json pricing block (plan USD fields or legacy micro fields) to DB shape."""
    usage_kind = pricing.get("usage_kind") or _usage_kind_for_model_type(model_type)
    source = str(pricing.get("source") or pricing.get("_price_source") or "catalog")

    def micro(field_micro: str, field_usd: str) -> int:
        if pricing.get(field_micro) is not None:
            return _int(pricing.get(field_micro))
        return _usd_per_million_to_micro(pricing.get(field_usd))

    audio_micro = _int(pricing.get("audio_micro_usd_per_second"))
    if not audio_micro:
        audio_micro = _usd_per_minute_to_micro_per_second(pricing.get("audio_per_minute"))

    tts_micro = _int(pricing.get("tts_micro_usd_per_million_chars"))
    if not tts_micro:
        tts_micro = _usd_per_million_to_micro(pricing.get("tts_per_1m_characters"))

    return {
        "usage_kind": usage_kind,
        "source": source,
        "currency": str(pricing.get("currency") or "USD"),
        "input_micro_usd_per_million": micro(
            "input_micro_usd_per_million", "input_per_1m"
        ),
        "output_micro_usd_per_million": micro(
            "output_micro_usd_per_million", "output_per_1m"
        ),
        "cache_read_micro_usd_per_million": micro(
            "cache_read_micro_usd_per_million", "cache_read_per_1m"
        ),
        "cache_creation_micro_usd_per_million": micro(
            "cache_creation_micro_usd_per_million", "cache_write_per_1m"
        ),
        "reasoning_micro_usd_per_million": micro(
            "reasoning_micro_usd_per_million", "reasoning_per_1m"
        ),
        "audio_micro_usd_per_second": audio_micro,
        "tts_micro_usd_per_million_chars": tts_micro,
    }


def _catalog_lookup_models(model: str, usage_kind: str) -> Tuple[str, ...]:
    candidates: List[str] = []
    for item in (
        model,
        f"azure-{model}" if not model.startswith("azure-") else model[len("azure-") :],
    ):
        if item and item not in candidates:
            candidates.append(item)
    return tuple(candidates)


def _scaled_cost(units: int, rate_per_million: int) -> int:
    if not units or not rate_per_million:
        return 0
    return (int(units) * int(rate_per_million)) // MICRO_USD_PER_UNIT


def metrics_from_deltas(deltas: Dict[str, Any]) -> UsageMetrics:
    return UsageMetrics(
        prompt_tokens=_int(deltas.get("prompt_tokens")),
        completion_tokens=_int(deltas.get("completion_tokens")),
        cache_read_tokens=_int(deltas.get("cache_read_tokens")),
        cache_creation_tokens=_int(deltas.get("cache_creation_tokens")),
        reasoning_tokens=_int(deltas.get("reasoning_tokens")),
        audio_seconds=_int(deltas.get("audio_seconds")),
        tts_characters=_int(deltas.get("tts_characters")),
    )


def cost_fields_from_deltas(
    deltas: Dict[str, Any],
    *,
    organization_id: UUID,
    model: str,
    usage_kind: str,
    usage_date: date,
    db: Session,
    resolver: Optional["PricingResolver"] = None,
) -> Dict[str, Any]:
    """Compute persisted cost columns for one pending-buffer delta row."""
    pricing = resolver or PricingResolver(db)
    rate = pricing.resolve_rate(
        organization_id=organization_id,
        model=model,
        usage_kind=usage_kind,
        usage_date=usage_date,
    )
    costs = compute_cost(metrics_from_deltas(deltas), rate)
    return {
        "input_cost_micro_usd": costs.input_cost_micro_usd,
        "output_cost_micro_usd": costs.output_cost_micro_usd,
        "cache_read_cost_micro_usd": costs.cache_read_cost_micro_usd,
        "cache_creation_cost_micro_usd": costs.cache_creation_cost_micro_usd,
        "reasoning_cost_micro_usd": costs.reasoning_cost_micro_usd,
        "audio_cost_micro_usd": costs.audio_cost_micro_usd,
        "tts_cost_micro_usd": costs.tts_cost_micro_usd,
        "total_cost_micro_usd": costs.total_cost_micro_usd,
        "pricing_rate_source": costs.pricing_rate_source,
        "pricing_rate_id": str(costs.pricing_rate_id)
        if costs.pricing_rate_id
        else None,
    }


def compute_cost(metrics: UsageMetrics, rate: Optional[RateCard]) -> CostBreakdown:
    if rate is None:
        return CostBreakdown()

    input_cost = _scaled_cost(metrics.prompt_tokens, rate.input_micro_usd_per_million)
    output_cost = _scaled_cost(
        metrics.completion_tokens, rate.output_micro_usd_per_million
    )
    cache_read_cost = _scaled_cost(
        metrics.cache_read_tokens, rate.cache_read_micro_usd_per_million
    )
    cache_creation_cost = _scaled_cost(
        metrics.cache_creation_tokens, rate.cache_creation_micro_usd_per_million
    )
    reasoning_cost = _scaled_cost(
        metrics.reasoning_tokens, rate.reasoning_micro_usd_per_million
    )
    audio_cost = 0
    if metrics.audio_seconds and rate.audio_micro_usd_per_second:
        audio_cost = int(metrics.audio_seconds) * int(rate.audio_micro_usd_per_second)
    tts_cost = _scaled_cost(
        metrics.tts_characters, rate.tts_micro_usd_per_million_chars
    )
    total = (
        input_cost
        + output_cost
        + cache_read_cost
        + cache_creation_cost
        + reasoning_cost
        + audio_cost
        + tts_cost
    )
    return CostBreakdown(
        input_cost_micro_usd=input_cost,
        output_cost_micro_usd=output_cost,
        cache_read_cost_micro_usd=cache_read_cost,
        cache_creation_cost_micro_usd=cache_creation_cost,
        reasoning_cost_micro_usd=reasoning_cost,
        audio_cost_micro_usd=audio_cost,
        tts_cost_micro_usd=tts_cost,
        total_cost_micro_usd=total,
        pricing_rate_source=rate.source,
        pricing_rate_id=rate.rate_id,
    )


def _rate_card_from_row(row: Any, *, source: str) -> RateCard:
    return RateCard(
        source=source,
        rate_id=row["id"],
        input_micro_usd_per_million=_int(row["input_micro_usd_per_million"]),
        output_micro_usd_per_million=_int(row["output_micro_usd_per_million"]),
        cache_read_micro_usd_per_million=_int(row["cache_read_micro_usd_per_million"]),
        cache_creation_micro_usd_per_million=_int(
            row["cache_creation_micro_usd_per_million"]
        ),
        reasoning_micro_usd_per_million=_int(row["reasoning_micro_usd_per_million"]),
        audio_micro_usd_per_second=_int(row["audio_micro_usd_per_second"]),
        tts_micro_usd_per_million_chars=_int(row["tts_micro_usd_per_million_chars"]),
    )


def _merge_override_with_catalog(
    override_row: Any, catalog: Optional[RateCard]
) -> RateCard:
    def pick(column: str, attr: str) -> int:
        value = override_row.get(column)
        if value is not None:
            return _int(value)
        if catalog is not None:
            return getattr(catalog, attr)
        return 0

    return RateCard(
        source=RATE_SOURCE_OVERRIDE,
        rate_id=override_row["id"],
        input_micro_usd_per_million=pick(
            "input_micro_usd_per_million", "input_micro_usd_per_million"
        ),
        output_micro_usd_per_million=pick(
            "output_micro_usd_per_million", "output_micro_usd_per_million"
        ),
        cache_read_micro_usd_per_million=pick(
            "cache_read_micro_usd_per_million", "cache_read_micro_usd_per_million"
        ),
        cache_creation_micro_usd_per_million=pick(
            "cache_creation_micro_usd_per_million",
            "cache_creation_micro_usd_per_million",
        ),
        reasoning_micro_usd_per_million=pick(
            "reasoning_micro_usd_per_million", "reasoning_micro_usd_per_million"
        ),
        audio_micro_usd_per_second=pick(
            "audio_micro_usd_per_second", "audio_micro_usd_per_second"
        ),
        tts_micro_usd_per_million_chars=pick(
            "tts_micro_usd_per_million_chars", "tts_micro_usd_per_million_chars"
        ),
    )


def _rate_card_to_cache_payload(card: RateCard) -> Dict[str, Any]:
    return {
        "source": card.source,
        "rate_id": str(card.rate_id),
        "input_micro_usd_per_million": card.input_micro_usd_per_million,
        "output_micro_usd_per_million": card.output_micro_usd_per_million,
        "cache_read_micro_usd_per_million": card.cache_read_micro_usd_per_million,
        "cache_creation_micro_usd_per_million": card.cache_creation_micro_usd_per_million,
        "reasoning_micro_usd_per_million": card.reasoning_micro_usd_per_million,
        "audio_micro_usd_per_second": card.audio_micro_usd_per_second,
        "tts_micro_usd_per_million_chars": card.tts_micro_usd_per_million_chars,
    }


def _rate_card_from_cache_payload(payload: Dict[str, Any]) -> RateCard:
    return RateCard(
        source=str(payload["source"]),
        rate_id=UUID(str(payload["rate_id"])),
        input_micro_usd_per_million=_int(payload.get("input_micro_usd_per_million")),
        output_micro_usd_per_million=_int(payload.get("output_micro_usd_per_million")),
        cache_read_micro_usd_per_million=_int(
            payload.get("cache_read_micro_usd_per_million")
        ),
        cache_creation_micro_usd_per_million=_int(
            payload.get("cache_creation_micro_usd_per_million")
        ),
        reasoning_micro_usd_per_million=_int(
            payload.get("reasoning_micro_usd_per_million")
        ),
        audio_micro_usd_per_second=_int(payload.get("audio_micro_usd_per_second")),
        tts_micro_usd_per_million_chars=_int(
            payload.get("tts_micro_usd_per_million_chars")
        ),
    )


class PricingResolver:
    """Cached pricing lookups for flush/recompute batches."""

    def __init__(self, db: Session):
        self._db = db
        self._memory_cache: Dict[Tuple[str, ...], Optional[RateCard]] = {}

    def resolve_rate(
        self,
        *,
        organization_id: UUID,
        model: str,
        usage_kind: str,
        usage_date: date,
    ) -> Optional[RateCard]:
        kind = usage_kind or USAGE_KIND_LLM
        memory_key = (str(organization_id), model, kind, usage_date.isoformat())
        if memory_key in self._memory_cache:
            return self._memory_cache[memory_key]

        redis_key = pricing_cache_key(
            organization_id=organization_id,
            model=model,
            usage_kind=kind,
            usage_date=usage_date,
        )
        cached = get_cached_rate_payload(redis_key)
        if cached:
            card = _rate_card_from_cache_payload(cached)
            self._memory_cache[memory_key] = card
            return card

        override = self._load_override_rate(organization_id, model, kind, usage_date)
        if override is not None:
            set_cached_rate_payload(redis_key, _rate_card_to_cache_payload(override))
            self._memory_cache[memory_key] = override
            return override

        catalog = self._resolve_catalog(model, kind, usage_date)
        set_cached_rate_payload(
            redis_key,
            _rate_card_to_cache_payload(catalog) if catalog else None,
        )
        self._memory_cache[memory_key] = catalog
        return catalog

    def _resolve_catalog(
        self, model: str, usage_kind: str, usage_date: date
    ) -> Optional[RateCard]:
        for candidate in _catalog_lookup_models(model, usage_kind):
            card = self._load_catalog_rate(candidate, usage_kind, usage_date)
            if card is not None:
                return card
        return None

    def _load_catalog_rate(
        self, model: str, usage_kind: str, usage_date: date
    ) -> Optional[RateCard]:
        table = _rates_table(self._db)
        row = self._db.execute(
            text(
                f"""
                SELECT
                    id,
                    input_micro_usd_per_million,
                    output_micro_usd_per_million,
                    cache_read_micro_usd_per_million,
                    cache_creation_micro_usd_per_million,
                    reasoning_micro_usd_per_million,
                    audio_micro_usd_per_second,
                    tts_micro_usd_per_million_chars
                FROM {table}
                WHERE model = :model
                  AND usage_kind = :usage_kind
                  AND effective_from <= :usage_date
                  AND (effective_to IS NULL OR effective_to >= :usage_date)
                ORDER BY effective_from DESC
                LIMIT 1
                """
            ),
            {
                "model": model,
                "usage_kind": usage_kind,
                "usage_date": usage_date.isoformat(),
            },
        ).mappings().first()
        if not row:
            return None
        return _rate_card_from_row(row, source=RATE_SOURCE_CATALOG)

    def _load_override_rate(
        self,
        organization_id: UUID,
        model: str,
        usage_kind: str,
        usage_date: date,
    ) -> Optional[RateCard]:
        row = self._db.execute(
            text(
                """
                SELECT
                    id,
                    input_micro_usd_per_million,
                    output_micro_usd_per_million,
                    cache_read_micro_usd_per_million,
                    cache_creation_micro_usd_per_million,
                    reasoning_micro_usd_per_million,
                    audio_micro_usd_per_second,
                    tts_micro_usd_per_million_chars
                FROM org_model_pricing_overrides
                WHERE organization_id = CAST(:organization_id AS uuid)
                  AND model = :model
                  AND usage_kind = :usage_kind
                  AND effective_from <= :usage_date
                  AND (effective_to IS NULL OR effective_to >= :usage_date)
                ORDER BY effective_from DESC
                LIMIT 1
                """
            ),
            {
                "organization_id": str(organization_id),
                "model": model,
                "usage_kind": usage_kind,
                "usage_date": usage_date.isoformat(),
            },
        ).mappings().first()
        if not row:
            return None
        catalog = self._resolve_catalog(model, usage_kind, usage_date)
        return _merge_override_with_catalog(row, catalog)


def _pricing_entries_from_models_json() -> Dict[str, Dict[str, Any]]:
    if not _MODELS_JSON_PATH.exists():
        return {}
    try:
        with open(_MODELS_JSON_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    entries: Dict[str, Dict[str, Any]] = {}
    for model_name, config in payload.items():
        if model_name.startswith("_") or not isinstance(config, dict):
            continue
        pricing = config.get("pricing")
        if not isinstance(pricing, dict):
            continue
        entries[model_name] = _normalize_pricing_block(
            pricing, model_type=config.get("model_type")
        )
    return entries


def seed_pricing_rates(db: Session, *, effective_from: Optional[date] = None) -> int:
    """Upsert global rates from models.json pricing blocks (seed only; DB is runtime truth)."""
    day = effective_from or DEFAULT_RATES_EFFECTIVE_FROM
    table = _rates_table(db)
    has_currency = (
        db.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = 'currency'
                """
            ),
            {"table_name": table},
        ).first()
        is not None
    )
    inserted = 0
    for model_name, pricing in _pricing_entries_from_models_json().items():
        usage_kind = pricing.get("usage_kind") or USAGE_KIND_LLM
        base_params = {
            "model": model_name,
            "usage_kind": usage_kind,
            "effective_from": day.isoformat(),
            "input_micro_usd_per_million": _int(
                pricing.get("input_micro_usd_per_million")
            ),
            "output_micro_usd_per_million": _int(
                pricing.get("output_micro_usd_per_million")
            ),
            "cache_read_micro_usd_per_million": _int(
                pricing.get("cache_read_micro_usd_per_million")
            ),
            "cache_creation_micro_usd_per_million": _int(
                pricing.get("cache_creation_micro_usd_per_million")
            ),
            "reasoning_micro_usd_per_million": _int(
                pricing.get("reasoning_micro_usd_per_million")
            ),
            "audio_micro_usd_per_second": _int(
                pricing.get("audio_micro_usd_per_second")
            ),
            "tts_micro_usd_per_million_chars": _int(
                pricing.get("tts_micro_usd_per_million_chars")
            ),
        }
        if has_currency:
            sql = f"""
                INSERT INTO {table} (
                    id, model, usage_kind, effective_from, currency, source,
                    input_micro_usd_per_million,
                    output_micro_usd_per_million,
                    cache_read_micro_usd_per_million,
                    cache_creation_micro_usd_per_million,
                    reasoning_micro_usd_per_million,
                    audio_micro_usd_per_second,
                    tts_micro_usd_per_million_chars,
                    created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), :model, :usage_kind, CAST(:effective_from AS date),
                    :currency, :source,
                    :input_micro_usd_per_million,
                    :output_micro_usd_per_million,
                    :cache_read_micro_usd_per_million,
                    :cache_creation_micro_usd_per_million,
                    :reasoning_micro_usd_per_million,
                    :audio_micro_usd_per_second,
                    :tts_micro_usd_per_million_chars,
                    now(), now()
                )
                ON CONFLICT (model, usage_kind, effective_from) DO UPDATE SET
                    currency = EXCLUDED.currency,
                    source = EXCLUDED.source,
                    input_micro_usd_per_million = EXCLUDED.input_micro_usd_per_million,
                    output_micro_usd_per_million = EXCLUDED.output_micro_usd_per_million,
                    cache_read_micro_usd_per_million = EXCLUDED.cache_read_micro_usd_per_million,
                    cache_creation_micro_usd_per_million = EXCLUDED.cache_creation_micro_usd_per_million,
                    reasoning_micro_usd_per_million = EXCLUDED.reasoning_micro_usd_per_million,
                    audio_micro_usd_per_second = EXCLUDED.audio_micro_usd_per_second,
                    tts_micro_usd_per_million_chars = EXCLUDED.tts_micro_usd_per_million_chars,
                    updated_at = now()
            """
            params = {
                **base_params,
                "currency": pricing.get("currency") or "USD",
                "source": _normalize_rate_source(pricing.get("source")),
            }
        else:
            sql = f"""
                INSERT INTO {table} (
                    id, model, usage_kind, effective_from,
                    input_micro_usd_per_million,
                    output_micro_usd_per_million,
                    cache_read_micro_usd_per_million,
                    cache_creation_micro_usd_per_million,
                    reasoning_micro_usd_per_million,
                    audio_micro_usd_per_second,
                    tts_micro_usd_per_million_chars,
                    created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), :model, :usage_kind, CAST(:effective_from AS date),
                    :input_micro_usd_per_million,
                    :output_micro_usd_per_million,
                    :cache_read_micro_usd_per_million,
                    :cache_creation_micro_usd_per_million,
                    :reasoning_micro_usd_per_million,
                    :audio_micro_usd_per_second,
                    :tts_micro_usd_per_million_chars,
                    now(), now()
                )
                ON CONFLICT (model, usage_kind, effective_from) DO UPDATE SET
                    input_micro_usd_per_million = EXCLUDED.input_micro_usd_per_million,
                    output_micro_usd_per_million = EXCLUDED.output_micro_usd_per_million,
                    cache_read_micro_usd_per_million = EXCLUDED.cache_read_micro_usd_per_million,
                    cache_creation_micro_usd_per_million = EXCLUDED.cache_creation_micro_usd_per_million,
                    reasoning_micro_usd_per_million = EXCLUDED.reasoning_micro_usd_per_million,
                    audio_micro_usd_per_second = EXCLUDED.audio_micro_usd_per_second,
                    tts_micro_usd_per_million_chars = EXCLUDED.tts_micro_usd_per_million_chars,
                    updated_at = now()
            """
            params = base_params
        result = db.execute(text(sql), params)
        if result.rowcount:
            inserted += 1
    if inserted:
        from app.services.usage.pricing_cache import invalidate_all_pricing_cache

        invalidate_all_pricing_cache()
    return inserted


def seed_pricing_catalog(db: Session, *, effective_from: Optional[date] = None) -> int:
    """Back-compat alias."""
    return seed_pricing_rates(db, effective_from=effective_from)


def apply_cost_to_bucket(
    db: Session,
    *,
    organization_id: UUID,
    bucket: Dict[str, Any],
    resolver: Optional[PricingResolver] = None,
) -> bool:
    """Recompute and persist cost columns for one rollup bucket from row totals."""
    context = bucket.get("context") or {}
    workspace_id = bucket.get("workspace_id")
    usage_kind = bucket.get("usage_kind") or USAGE_KIND_LLM
    usage_date = bucket["usage_date"]
    if isinstance(usage_date, str):
        usage_date = date.fromisoformat(usage_date)

    base_params = {
        "organization_id": str(organization_id),
        "workspace_id": str(workspace_id) if workspace_id else None,
        "product_section": bucket["product_section"],
        "model": bucket["model"],
        "usage_date": usage_date.isoformat(),
        "usage_kind": usage_kind,
    }
    exact_params = {
        **base_params,
        "context": json.dumps(context),
        "context_resource_id": str(context.get("resource_id") or ""),
        "context_resource_type": str(context.get("resource_type") or ""),
    }
    row = db.execute(
        text(
            """
            SELECT
                prompt_tokens, completion_tokens, cache_read_tokens,
                cache_creation_tokens, reasoning_tokens, audio_seconds,
                tts_characters
            FROM llm_usage_daily
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND product_section = :product_section
              AND model = :model
              AND usage_date = CAST(:usage_date AS date)
              AND usage_kind = :usage_kind
              AND workspace_id IS NOT DISTINCT FROM CAST(:workspace_id AS uuid)
              AND context = CAST(:context AS jsonb)
            """
        ),
        exact_params,
    ).mappings().first()
    if not row:
        row = db.execute(
            text(
                """
                SELECT
                    prompt_tokens, completion_tokens, cache_read_tokens,
                    cache_creation_tokens, reasoning_tokens, audio_seconds,
                    tts_characters
                FROM llm_usage_daily
                WHERE organization_id = CAST(:organization_id AS uuid)
                  AND product_section = :product_section
                  AND model = :model
                  AND usage_date = CAST(:usage_date AS date)
                  AND usage_kind = :usage_kind
                  AND workspace_id IS NOT DISTINCT FROM CAST(:workspace_id AS uuid)
                  AND COALESCE(context->>'resource_id', '') = :context_resource_id
                  AND COALESCE(context->>'resource_type', '') = :context_resource_type
                """
            ),
            exact_params,
        ).mappings().first()
    if not row:
        return False

    pricing = resolver or PricingResolver(db)
    rate = pricing.resolve_rate(
        organization_id=organization_id,
        model=bucket["model"],
        usage_kind=usage_kind,
        usage_date=usage_date,
    )
    costs = compute_cost(
        UsageMetrics(
            prompt_tokens=_int(row["prompt_tokens"]),
            completion_tokens=_int(row["completion_tokens"]),
            cache_read_tokens=_int(row["cache_read_tokens"]),
            cache_creation_tokens=_int(row["cache_creation_tokens"]),
            reasoning_tokens=_int(row["reasoning_tokens"]),
            audio_seconds=_int(row["audio_seconds"]),
            tts_characters=_int(row["tts_characters"]),
        ),
        rate,
    )
    update_params = {
        **exact_params,
        "input_cost_micro_usd": costs.input_cost_micro_usd,
        "output_cost_micro_usd": costs.output_cost_micro_usd,
        "cache_read_cost_micro_usd": costs.cache_read_cost_micro_usd,
        "cache_creation_cost_micro_usd": costs.cache_creation_cost_micro_usd,
        "reasoning_cost_micro_usd": costs.reasoning_cost_micro_usd,
        "audio_cost_micro_usd": costs.audio_cost_micro_usd,
        "tts_cost_micro_usd": costs.tts_cost_micro_usd,
        "total_cost_micro_usd": costs.total_cost_micro_usd,
        "pricing_rate_source": costs.pricing_rate_source,
        "pricing_rate_id": str(costs.pricing_rate_id)
        if costs.pricing_rate_id
        else None,
    }
    result = db.execute(
        text(
            """
            UPDATE llm_usage_daily SET
                input_cost_micro_usd = :input_cost_micro_usd,
                output_cost_micro_usd = :output_cost_micro_usd,
                cache_read_cost_micro_usd = :cache_read_cost_micro_usd,
                cache_creation_cost_micro_usd = :cache_creation_cost_micro_usd,
                reasoning_cost_micro_usd = :reasoning_cost_micro_usd,
                audio_cost_micro_usd = :audio_cost_micro_usd,
                tts_cost_micro_usd = :tts_cost_micro_usd,
                total_cost_micro_usd = :total_cost_micro_usd,
                pricing_rate_source = :pricing_rate_source,
                pricing_rate_id = CAST(:pricing_rate_id AS uuid),
                updated_at = now()
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND product_section = :product_section
              AND model = :model
              AND usage_date = CAST(:usage_date AS date)
              AND usage_kind = :usage_kind
              AND workspace_id IS NOT DISTINCT FROM CAST(:workspace_id AS uuid)
              AND context = CAST(:context AS jsonb)
            """
        ),
        update_params,
    )
    if result.rowcount:
        return True
    result = db.execute(
        text(
            """
            UPDATE llm_usage_daily SET
                input_cost_micro_usd = :input_cost_micro_usd,
                output_cost_micro_usd = :output_cost_micro_usd,
                cache_read_cost_micro_usd = :cache_read_cost_micro_usd,
                cache_creation_cost_micro_usd = :cache_creation_cost_micro_usd,
                reasoning_cost_micro_usd = :reasoning_cost_micro_usd,
                audio_cost_micro_usd = :audio_cost_micro_usd,
                tts_cost_micro_usd = :tts_cost_micro_usd,
                total_cost_micro_usd = :total_cost_micro_usd,
                pricing_rate_source = :pricing_rate_source,
                pricing_rate_id = CAST(:pricing_rate_id AS uuid),
                updated_at = now()
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND product_section = :product_section
              AND model = :model
              AND usage_date = CAST(:usage_date AS date)
              AND usage_kind = :usage_kind
              AND workspace_id IS NOT DISTINCT FROM CAST(:workspace_id AS uuid)
              AND COALESCE(context->>'resource_id', '') = :context_resource_id
              AND COALESCE(context->>'resource_type', '') = :context_resource_type
            """
        ),
        update_params,
    )
    return bool(result.rowcount)


def recompute_usage_costs(
    db: Session,
    *,
    organization_id: Optional[UUID] = None,
    model: Optional[str] = None,
    usage_kind: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    batch_size: int = 500,
    on_progress: Optional[Callable[[int], None]] = None,
) -> int:
    """Recompute stored costs for existing rollup rows (backfill / override changes)."""
    resolver = PricingResolver(db)
    updated = 0
    last_id: Optional[str] = None

    while True:
        params: Dict[str, Any] = {"batch_size": batch_size}
        filters = ["1=1"]
        if organization_id is not None:
            filters.append("organization_id = CAST(:organization_id AS uuid)")
            params["organization_id"] = str(organization_id)
        if model is not None:
            filters.append("model = :model")
            params["model"] = model
        if usage_kind is not None:
            filters.append("usage_kind = :usage_kind")
            params["usage_kind"] = usage_kind
        if start_date is not None:
            filters.append("usage_date >= CAST(:start_date AS date)")
            params["start_date"] = start_date.isoformat()
        if end_date is not None:
            filters.append("usage_date <= CAST(:end_date AS date)")
            params["end_date"] = end_date.isoformat()
        if last_id is not None:
            filters.append("id > CAST(:last_id AS uuid)")
            params["last_id"] = last_id

        rows = db.execute(
            text(
                f"""
                SELECT
                    id, organization_id, workspace_id, product_section, model,
                    context, usage_date, usage_kind
                FROM llm_usage_daily
                WHERE {' AND '.join(filters)}
                ORDER BY id
                LIMIT :batch_size
                """
            ),
            params,
        ).mappings().all()
        if not rows:
            break

        for row in rows:
            bucket = {
                "workspace_id": row["workspace_id"],
                "product_section": row["product_section"],
                "model": row["model"],
                "context": row["context"] or {},
                "usage_date": row["usage_date"],
                "usage_kind": row["usage_kind"] or USAGE_KIND_LLM,
            }
            if apply_cost_to_bucket(
                db,
                organization_id=row["organization_id"],
                bucket=bucket,
                resolver=resolver,
            ):
                updated += 1
            last_id = str(row["id"])

        db.commit()
        if on_progress is not None:
            on_progress(updated)

    if on_progress is not None:
        on_progress(updated)

    return updated
