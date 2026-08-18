"""Migration: usage pricing catalog, org overrides, and cost columns on rollups."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add model_pricing_catalog, org_model_pricing_overrides, usage_pricing_mode, "
    "and cost columns on llm_usage_daily"
)


def _table_exists(db: Session, table: str) -> bool:
    return (
        db.execute(
            text(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_name = :table_name
                """
            ),
            {"table_name": table},
        ).first()
        is not None
    )


def _column_exists(db: Session, table: str, column: str) -> bool:
    return (
        db.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = :column_name
                """
            ),
            {"table_name": table, "column_name": column},
        ).first()
        is not None
    )


def _seed_pricing_catalog(db: Session) -> int:
    from app.services.usage.pricing import DEFAULT_CATALOG_EFFECTIVE_FROM, seed_pricing_catalog

    return seed_pricing_catalog(db, effective_from=DEFAULT_CATALOG_EFFECTIVE_FROM)


def upgrade(db: Session):
    if not _column_exists(db, "organizations", "usage_pricing_mode"):
        db.execute(
            text(
                """
                ALTER TABLE organizations
                ADD COLUMN usage_pricing_mode VARCHAR(32) NOT NULL DEFAULT 'platform_managed'
                """
            )
        )
        print("Added organizations.usage_pricing_mode")

    if not _table_exists(db, "model_pricing_catalog"):
        db.execute(
            text(
                """
                CREATE TABLE model_pricing_catalog (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    model VARCHAR(255) NOT NULL,
                    usage_kind VARCHAR(16) NOT NULL DEFAULT 'llm',
                    effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
                    effective_to DATE,
                    input_micro_usd_per_million BIGINT NOT NULL DEFAULT 0,
                    output_micro_usd_per_million BIGINT NOT NULL DEFAULT 0,
                    cache_read_micro_usd_per_million BIGINT NOT NULL DEFAULT 0,
                    cache_creation_micro_usd_per_million BIGINT NOT NULL DEFAULT 0,
                    reasoning_micro_usd_per_million BIGINT NOT NULL DEFAULT 0,
                    audio_micro_usd_per_second BIGINT NOT NULL DEFAULT 0,
                    tts_micro_usd_per_million_chars BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT uq_model_pricing_catalog_model_kind_from
                        UNIQUE (model, usage_kind, effective_from)
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX ix_model_pricing_catalog_lookup
                ON model_pricing_catalog (model, usage_kind, effective_from DESC)
                """
            )
        )
        print("Created model_pricing_catalog")

    if not _table_exists(db, "org_model_pricing_overrides"):
        db.execute(
            text(
                """
                CREATE TABLE org_model_pricing_overrides (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL
                        REFERENCES organizations(id) ON DELETE CASCADE,
                    model VARCHAR(255) NOT NULL,
                    usage_kind VARCHAR(16) NOT NULL DEFAULT 'llm',
                    effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
                    effective_to DATE,
                    input_micro_usd_per_million BIGINT,
                    output_micro_usd_per_million BIGINT,
                    cache_read_micro_usd_per_million BIGINT,
                    cache_creation_micro_usd_per_million BIGINT,
                    reasoning_micro_usd_per_million BIGINT,
                    audio_micro_usd_per_second BIGINT,
                    tts_micro_usd_per_million_chars BIGINT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT uq_org_model_pricing_override
                        UNIQUE (organization_id, model, usage_kind, effective_from)
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX ix_org_model_pricing_overrides_lookup
                ON org_model_pricing_overrides (
                    organization_id, model, usage_kind, effective_from DESC
                )
                """
            )
        )
        print("Created org_model_pricing_overrides")

    cost_columns = [
        ("input_cost_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
        ("output_cost_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
        ("cache_read_cost_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
        ("cache_creation_cost_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
        ("reasoning_cost_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
        ("audio_cost_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
        ("tts_cost_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
        ("total_cost_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
        ("pricing_rate_source", "VARCHAR(16)"),
        ("pricing_rate_id", "UUID"),
    ]
    if _table_exists(db, "llm_usage_daily"):
        for column, col_type in cost_columns:
            if not _column_exists(db, "llm_usage_daily", column):
                db.execute(
                    text(
                        f"ALTER TABLE llm_usage_daily ADD COLUMN {column} {col_type}"
                    )
                )
        print("Added cost columns to llm_usage_daily")

    db.commit()

    if _table_exists(db, "model_pricing_catalog"):
        seeded = _seed_pricing_catalog(db)
        if seeded:
            print(f"Seeded {seeded} model pricing catalog row(s)")
        db.commit()


def downgrade(db: Session):
    if _table_exists(db, "llm_usage_daily"):
        for column in (
            "input_cost_micro_usd",
            "output_cost_micro_usd",
            "cache_read_cost_micro_usd",
            "cache_creation_cost_micro_usd",
            "reasoning_cost_micro_usd",
            "audio_cost_micro_usd",
            "tts_cost_micro_usd",
            "total_cost_micro_usd",
            "pricing_rate_source",
            "pricing_rate_id",
        ):
            if _column_exists(db, "llm_usage_daily", column):
                db.execute(text(f"ALTER TABLE llm_usage_daily DROP COLUMN {column}"))

    db.execute(text("DROP TABLE IF EXISTS org_model_pricing_overrides"))
    db.execute(text("DROP TABLE IF EXISTS model_pricing_catalog"))

    if _column_exists(db, "organizations", "usage_pricing_mode"):
        db.execute(text("ALTER TABLE organizations DROP COLUMN usage_pricing_mode"))

    db.commit()
