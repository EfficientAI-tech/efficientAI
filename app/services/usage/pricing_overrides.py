"""Org-level usage pricing overrides."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.usage.pricing import (
    PricingResolver,
    USAGE_KIND_LLM,
    USAGE_KIND_STT,
    USAGE_KIND_TTS,
    _int,
    _pricing_entries_from_models_json,
    _rates_table,
    _usd_per_million_to_micro,
    _usd_per_minute_to_micro_per_second,
)
from app.services.usage.pricing_cache import invalidate_org_pricing_cache
from app.services.usage.pricing_jobs import create_recompute_job, enqueue_recompute_job
from app.services.usage.usage_costs import micro_to_usd

RATE_COLUMNS = (
    "input_micro_usd_per_million",
    "output_micro_usd_per_million",
    "cache_read_micro_usd_per_million",
    "cache_creation_micro_usd_per_million",
    "reasoning_micro_usd_per_million",
    "audio_micro_usd_per_second",
    "tts_micro_usd_per_million_chars",
)

USD_RATE_FIELDS = {
    "input_per_1m": "input_micro_usd_per_million",
    "output_per_1m": "output_micro_usd_per_million",
    "cache_read_per_1m": "cache_read_micro_usd_per_million",
    "cache_write_per_1m": "cache_creation_micro_usd_per_million",
    "reasoning_per_1m": "reasoning_micro_usd_per_million",
    "audio_per_minute": "audio_micro_usd_per_second",
    "tts_per_1m_characters": "tts_micro_usd_per_million_chars",
}


def _known_models(db: Session) -> Set[str]:
    models = set(_pricing_entries_from_models_json().keys())
    table = _rates_table(db)
    rows = db.execute(text(f"SELECT DISTINCT model FROM {table}")).scalars().all()
    models.update(rows)
    return models


def validate_model_name(
    db: Session,
    model: str,
    *,
    organization_id: Optional[UUID] = None,
) -> None:
    from app.services.usage.enabled_models import org_pricing_eligible_models

    if organization_id is not None:
        eligible = set(org_pricing_eligible_models(db, organization_id))
        if model in eligible:
            return
    if model in _known_models(db):
        return
    raise HTTPException(status_code=400, detail=f"Unknown model: {model}")


def _validate_usage_kind(usage_kind: str) -> str:
    kind = usage_kind or USAGE_KIND_LLM
    if kind not in {USAGE_KIND_LLM, USAGE_KIND_STT, USAGE_KIND_TTS}:
        raise HTTPException(status_code=400, detail=f"Invalid usage_kind: {kind}")
    return kind


def _micro_to_optional_usd_per_1m(micro: Optional[int]) -> Optional[float]:
    if micro is None:
        return None
    return micro_to_usd(_int(micro))


def _micro_to_optional_usd_per_minute(micro_per_second: Optional[int]) -> Optional[float]:
    if micro_per_second is None:
        return None
    return micro_to_usd(_int(micro_per_second) * 60)


def _rates_usd_from_row(row: Dict[str, Any]) -> Dict[str, Optional[float]]:
    return {
        "input_per_1m": _micro_to_optional_usd_per_1m(row.get("input_micro_usd_per_million")),
        "output_per_1m": _micro_to_optional_usd_per_1m(row.get("output_micro_usd_per_million")),
        "cache_read_per_1m": _micro_to_optional_usd_per_1m(
            row.get("cache_read_micro_usd_per_million")
        ),
        "cache_write_per_1m": _micro_to_optional_usd_per_1m(
            row.get("cache_creation_micro_usd_per_million")
        ),
        "reasoning_per_1m": _micro_to_optional_usd_per_1m(
            row.get("reasoning_micro_usd_per_million")
        ),
        "audio_per_minute": _micro_to_optional_usd_per_minute(
            row.get("audio_micro_usd_per_second")
        ),
        "tts_per_1m_characters": _micro_to_optional_usd_per_1m(
            row.get("tts_micro_usd_per_million_chars")
        ),
    }


def _rate_card_to_usd_dict(card) -> Dict[str, float]:
    return {
        "input_per_1m": micro_to_usd(card.input_micro_usd_per_million),
        "output_per_1m": micro_to_usd(card.output_micro_usd_per_million),
        "cache_read_per_1m": micro_to_usd(card.cache_read_micro_usd_per_million),
        "cache_write_per_1m": micro_to_usd(card.cache_creation_micro_usd_per_million),
        "reasoning_per_1m": micro_to_usd(card.reasoning_micro_usd_per_million),
        "audio_per_minute": micro_to_usd(card.audio_micro_usd_per_second * 60),
        "tts_per_1m_characters": micro_to_usd(card.tts_micro_usd_per_million_chars),
    }


def _override_row_to_dict(row: Any) -> Dict[str, Any]:
    payload = dict(row)
    for key in ("id", "organization_id"):
        if payload.get(key) is not None:
            payload[key] = str(payload[key])
    rates = _rates_usd_from_row(payload)
    return {
        "id": payload["id"],
        "organization_id": payload["organization_id"],
        "model": payload["model"],
        "usage_kind": payload["usage_kind"],
        "effective_from": payload["effective_from"],
        "effective_to": payload.get("effective_to"),
        "rates": rates,
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }


def _usd_payload_to_micro_columns(payload: Dict[str, Any]) -> Dict[str, Optional[int]]:
    columns: Dict[str, Optional[int]] = {}
    for usd_field, micro_column in USD_RATE_FIELDS.items():
        if usd_field not in payload:
            continue
        value = payload.get(usd_field)
        if value is None:
            columns[micro_column] = None
            continue
        if usd_field == "audio_per_minute":
            columns[micro_column] = _usd_per_minute_to_micro_per_second(value)
        else:
            columns[micro_column] = _usd_per_million_to_micro(value)
    return columns


def list_overrides(
    db: Session,
    *,
    organization_id: UUID,
    model: Optional[str] = None,
    usage_kind: Optional[str] = None,
) -> List[Dict[str, Any]]:
    filters = ["organization_id = CAST(:organization_id AS uuid)"]
    params: Dict[str, Any] = {"organization_id": str(organization_id)}
    if model is not None:
        filters.append("model = :model")
        params["model"] = model
    if usage_kind is not None:
        filters.append("usage_kind = :usage_kind")
        params["usage_kind"] = _validate_usage_kind(usage_kind)

    rows = db.execute(
        text(
            f"""
            SELECT *
            FROM org_model_pricing_overrides
            WHERE {' AND '.join(filters)}
            ORDER BY model ASC, usage_kind ASC, effective_from DESC
            """
        ),
        params,
    ).mappings().all()
    return [_override_row_to_dict(row) for row in rows]


def get_effective_rate(
    db: Session,
    *,
    organization_id: UUID,
    model: str,
    usage_kind: str,
    as_of: date,
) -> Dict[str, Any]:
    validate_model_name(db, model, organization_id=organization_id)
    kind = _validate_usage_kind(usage_kind)
    resolver = PricingResolver(db)
    effective = resolver.resolve_rate(
        organization_id=organization_id,
        model=model,
        usage_kind=kind,
        usage_date=as_of,
    )
    catalog = resolver._resolve_catalog(model, kind, as_of)
    override_row = db.execute(
        text(
            """
            SELECT *
            FROM org_model_pricing_overrides
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND model = :model
              AND usage_kind = :usage_kind
              AND effective_from <= :as_of
              AND (effective_to IS NULL OR effective_to >= :as_of)
            ORDER BY effective_from DESC
            LIMIT 1
            """
        ),
        {
            "organization_id": str(organization_id),
            "model": model,
            "usage_kind": kind,
            "as_of": as_of.isoformat(),
        },
    ).mappings().first()

    return {
        "model": model,
        "usage_kind": kind,
        "as_of": as_of,
        "catalog_rates": _rate_card_to_usd_dict(catalog) if catalog else None,
        "catalog_rate_id": str(catalog.rate_id) if catalog else None,
        "override": _override_row_to_dict(override_row) if override_row else None,
        "effective_rates": _rate_card_to_usd_dict(effective) if effective else None,
        "effective_source": effective.source if effective else None,
        "effective_rate_id": str(effective.rate_id) if effective else None,
        "has_override": override_row is not None,
    }


def list_effective_pricing(
    db: Session,
    *,
    organization_id: UUID,
    usage_kind: Optional[str] = None,
    model: Optional[str] = None,
    as_of: date,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    if model:
        return [
            get_effective_rate(
                db,
                organization_id=organization_id,
                model=model,
                usage_kind=usage_kind or USAGE_KIND_LLM,
                as_of=as_of,
            )
        ]

    keys: Set[tuple[str, str]] = set()
    for entry in list_overrides(db, organization_id=organization_id, usage_kind=usage_kind):
        keys.add((entry["model"], entry["usage_kind"]))

    table = _rates_table(db)
    rate_filters = ["effective_from <= :as_of", "(effective_to IS NULL OR effective_to >= :as_of)"]
    params: Dict[str, Any] = {"as_of": as_of.isoformat(), "limit": limit}
    if usage_kind is not None:
        rate_filters.append("usage_kind = :usage_kind")
        params["usage_kind"] = _validate_usage_kind(usage_kind)
    rate_rows = db.execute(
        text(
            f"""
            SELECT DISTINCT model, usage_kind
            FROM {table}
            WHERE {' AND '.join(rate_filters)}
            ORDER BY model ASC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    for row in rate_rows:
        keys.add((row["model"], row["usage_kind"]))

    results: List[Dict[str, Any]] = []
    for model_name, kind in sorted(keys)[:limit]:
        results.append(
            get_effective_rate(
                db,
                organization_id=organization_id,
                model=model_name,
                usage_kind=kind,
                as_of=as_of,
            )
        )
    return results


def upsert_override(
    db: Session,
    *,
    organization_id: UUID,
    model: str,
    usage_kind: str,
    effective_from: date,
    effective_to: Optional[date] = None,
    rates: Dict[str, Any],
    recompute: bool = True,
) -> Dict[str, Any]:
    validate_model_name(db, model, organization_id=organization_id)
    kind = _validate_usage_kind(usage_kind)
    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(status_code=400, detail="effective_to must be >= effective_from")

    micro_columns = _usd_payload_to_micro_columns(rates)
    if not micro_columns:
        raise HTTPException(status_code=400, detail="At least one rate field is required")

    params: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "model": model,
        "usage_kind": kind,
        "effective_from": effective_from.isoformat(),
        "effective_to": effective_to.isoformat() if effective_to else None,
    }
    for column in RATE_COLUMNS:
        params[column] = micro_columns.get(column)

    row = db.execute(
        text(
            """
            INSERT INTO org_model_pricing_overrides (
                organization_id, model, usage_kind, effective_from, effective_to,
                input_micro_usd_per_million, output_micro_usd_per_million,
                cache_read_micro_usd_per_million, cache_creation_micro_usd_per_million,
                reasoning_micro_usd_per_million, audio_micro_usd_per_second,
                tts_micro_usd_per_million_chars
            ) VALUES (
                CAST(:organization_id AS uuid), :model, :usage_kind,
                CAST(:effective_from AS date), CAST(:effective_to AS date),
                :input_micro_usd_per_million, :output_micro_usd_per_million,
                :cache_read_micro_usd_per_million, :cache_creation_micro_usd_per_million,
                :reasoning_micro_usd_per_million, :audio_micro_usd_per_second,
                :tts_micro_usd_per_million_chars
            )
            ON CONFLICT (organization_id, model, usage_kind, effective_from)
            DO UPDATE SET
                effective_to = EXCLUDED.effective_to,
                input_micro_usd_per_million = COALESCE(
                    EXCLUDED.input_micro_usd_per_million,
                    org_model_pricing_overrides.input_micro_usd_per_million
                ),
                output_micro_usd_per_million = COALESCE(
                    EXCLUDED.output_micro_usd_per_million,
                    org_model_pricing_overrides.output_micro_usd_per_million
                ),
                cache_read_micro_usd_per_million = COALESCE(
                    EXCLUDED.cache_read_micro_usd_per_million,
                    org_model_pricing_overrides.cache_read_micro_usd_per_million
                ),
                cache_creation_micro_usd_per_million = COALESCE(
                    EXCLUDED.cache_creation_micro_usd_per_million,
                    org_model_pricing_overrides.cache_creation_micro_usd_per_million
                ),
                reasoning_micro_usd_per_million = COALESCE(
                    EXCLUDED.reasoning_micro_usd_per_million,
                    org_model_pricing_overrides.reasoning_micro_usd_per_million
                ),
                audio_micro_usd_per_second = COALESCE(
                    EXCLUDED.audio_micro_usd_per_second,
                    org_model_pricing_overrides.audio_micro_usd_per_second
                ),
                tts_micro_usd_per_million_chars = COALESCE(
                    EXCLUDED.tts_micro_usd_per_million_chars,
                    org_model_pricing_overrides.tts_micro_usd_per_million_chars
                ),
                updated_at = now()
            RETURNING *
            """
        ),
        params,
    ).mappings().first()
    db.commit()

    invalidate_org_pricing_cache(organization_id)

    recompute_job_id = None
    recompute_enqueued = False
    if recompute:
        recompute_job_id = _enqueue_override_recompute(
            db,
            organization_id=organization_id,
            model=model,
            usage_kind=kind,
            start_date=effective_from,
            end_date=effective_to,
        )
        recompute_enqueued = recompute_job_id is not None

    result = _override_row_to_dict(row)
    result["recompute_enqueued"] = recompute_enqueued
    result["recompute_job_id"] = recompute_job_id
    return result


def delete_override(
    db: Session,
    *,
    organization_id: UUID,
    model: str,
    usage_kind: str,
    effective_from: Optional[date] = None,
    recompute: bool = True,
) -> Dict[str, Any]:
    validate_model_name(db, model, organization_id=organization_id)
    kind = _validate_usage_kind(usage_kind)
    filters = [
        "organization_id = CAST(:organization_id AS uuid)",
        "model = :model",
        "usage_kind = :usage_kind",
    ]
    params: Dict[str, Any] = {
        "organization_id": str(organization_id),
        "model": model,
        "usage_kind": kind,
    }

    if effective_from is not None:
        filters.append("effective_from = CAST(:effective_from AS date)")
        params["effective_from"] = effective_from.isoformat()
        result = db.execute(
            text(
                f"""
                DELETE FROM org_model_pricing_overrides
                WHERE {' AND '.join(filters)}
                RETURNING effective_from, effective_to
                """
            ),
            params,
        ).mappings().first()
        if not result:
            raise HTTPException(status_code=404, detail="Override not found")
        recompute_from = effective_from
        recompute_to = result.get("effective_to")
        db.commit()
    else:
        active = db.execute(
            text(
                f"""
                SELECT id, effective_from, effective_to
                FROM org_model_pricing_overrides
                WHERE {' AND '.join(filters)}
                  AND effective_from <= CURRENT_DATE
                  AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
                ORDER BY effective_from DESC
                LIMIT 1
                """
            ),
            params,
        ).mappings().first()
        if not active:
            raise HTTPException(status_code=404, detail="No active override found")
        recompute_from = active["effective_from"]
        recompute_to = active.get("effective_to")
        yesterday = date.today() - timedelta(days=1)
        if active["effective_from"] > yesterday:
            db.execute(
                text(
                    """
                    DELETE FROM org_model_pricing_overrides
                    WHERE id = CAST(:id AS uuid)
                    """
                ),
                {"id": str(active["id"])},
            )
        else:
            db.execute(
                text(
                    """
                    UPDATE org_model_pricing_overrides
                    SET effective_to = CAST(:effective_to AS date), updated_at = now()
                    WHERE id = CAST(:id AS uuid)
                    """
                ),
                {"id": str(active["id"]), "effective_to": yesterday.isoformat()},
            )
        db.commit()

    invalidate_org_pricing_cache(organization_id)

    recompute_job_id = None
    recompute_enqueued = False
    if recompute:
        recompute_job_id = _enqueue_override_recompute(
            db,
            organization_id=organization_id,
            model=model,
            usage_kind=kind,
            start_date=recompute_from,
            end_date=recompute_to,
        )
        recompute_enqueued = recompute_job_id is not None

    return {
        "deleted": True,
        "model": model,
        "usage_kind": kind,
        "recompute_enqueued": recompute_enqueued,
        "recompute_job_id": recompute_job_id,
    }


def _enqueue_override_recompute(
    db: Session,
    *,
    organization_id: UUID,
    model: str,
    usage_kind: str,
    start_date: date,
    end_date: Optional[date],
) -> Optional[str]:
    try:
        job = create_recompute_job(
            db,
            organization_id=organization_id,
            model=model,
            usage_kind=usage_kind,
            start_date=start_date,
            end_date=end_date,
        )
        enqueue_recompute_job(db, job)
        return str(job.id)
    except HTTPException as exc:
        if exc.status_code == 409:
            return None
        raise
