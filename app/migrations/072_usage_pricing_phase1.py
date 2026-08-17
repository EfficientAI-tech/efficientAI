"""Migration: Phase 1 plan alignment — model_pricing_rates, buffer costs, strip extras."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Rename model_pricing_catalog to model_pricing_rates, add currency/source, "
    "cost columns on usage_pending_buffer, drop margin/BYOK org columns"
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


def _ensure_model_pricing_rates(db: Session) -> None:
    if _table_exists(db, "model_pricing_catalog") and not _table_exists(
        db, "model_pricing_rates"
    ):
        db.execute(
            text("ALTER TABLE model_pricing_catalog RENAME TO model_pricing_rates")
        )
        db.execute(
            text(
                """
                ALTER INDEX IF EXISTS uq_model_pricing_catalog_model_kind_from
                RENAME TO uq_model_pricing_rates_model_kind_from
                """
            )
        )
        db.execute(
            text(
                """
                ALTER INDEX IF EXISTS ix_model_pricing_catalog_lookup
                RENAME TO ix_model_pricing_rates_lookup
                """
            )
        )
        print("Renamed model_pricing_catalog -> model_pricing_rates")

    if not _table_exists(db, "model_pricing_rates"):
        db.execute(
            text(
                """
                CREATE TABLE model_pricing_rates (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    model VARCHAR(255) NOT NULL,
                    usage_kind VARCHAR(16) NOT NULL DEFAULT 'llm',
                    effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
                    effective_to DATE,
                    currency VARCHAR(8) NOT NULL DEFAULT 'USD',
                    source VARCHAR(255) NOT NULL DEFAULT 'catalog',
                    input_micro_usd_per_million BIGINT NOT NULL DEFAULT 0,
                    output_micro_usd_per_million BIGINT NOT NULL DEFAULT 0,
                    cache_read_micro_usd_per_million BIGINT NOT NULL DEFAULT 0,
                    cache_creation_micro_usd_per_million BIGINT NOT NULL DEFAULT 0,
                    reasoning_micro_usd_per_million BIGINT NOT NULL DEFAULT 0,
                    audio_micro_usd_per_second BIGINT NOT NULL DEFAULT 0,
                    tts_micro_usd_per_million_chars BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT uq_model_pricing_rates_model_kind_from
                        UNIQUE (model, usage_kind, effective_from)
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX ix_model_pricing_rates_lookup
                ON model_pricing_rates (model, usage_kind, effective_from DESC)
                """
            )
        )
        print("Created model_pricing_rates")

    if not _column_exists(db, "model_pricing_rates", "currency"):
        db.execute(
            text(
                """
                ALTER TABLE model_pricing_rates
                ADD COLUMN currency VARCHAR(8) NOT NULL DEFAULT 'USD'
                """
            )
        )
    if not _column_exists(db, "model_pricing_rates", "source"):
        db.execute(
            text(
                """
                ALTER TABLE model_pricing_rates
                ADD COLUMN source VARCHAR(255) NOT NULL DEFAULT 'catalog'
                """
            )
        )


def _widen_source_column(db: Session) -> None:
    if not _table_exists(db, "model_pricing_rates"):
        return
    if not _column_exists(db, "model_pricing_rates", "source"):
        return
    db.execute(
        text(
            """
            ALTER TABLE model_pricing_rates
            ALTER COLUMN source TYPE VARCHAR(255)
            """
        )
    )
    print("Widened model_pricing_rates.source to VARCHAR(255)")


def _add_buffer_cost_columns(db: Session) -> None:
    if not _table_exists(db, "usage_pending_buffer"):
        return
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
    for column, col_type in cost_columns:
        if not _column_exists(db, "usage_pending_buffer", column):
            db.execute(
                text(
                    f"ALTER TABLE usage_pending_buffer ADD COLUMN {column} {col_type}"
                )
            )
    print("Ensured cost columns on usage_pending_buffer")


def _strip_org_extras(db: Session) -> None:
    if _column_exists(db, "organizations", "usage_margin_multiplier"):
        db.execute(
            text("ALTER TABLE organizations DROP COLUMN usage_margin_multiplier")
        )
        print("Dropped organizations.usage_margin_multiplier")
    if _column_exists(db, "organizations", "usage_pricing_mode"):
        db.execute(text("ALTER TABLE organizations DROP COLUMN usage_pricing_mode"))
        print("Dropped organizations.usage_pricing_mode")


def upgrade(db: Session):
    _ensure_model_pricing_rates(db)
    _widen_source_column(db)
    _add_buffer_cost_columns(db)
    _strip_org_extras(db)
    db.commit()

    from app.services.usage.pricing import DEFAULT_RATES_EFFECTIVE_FROM, seed_pricing_rates

    seeded = seed_pricing_rates(db, effective_from=DEFAULT_RATES_EFFECTIVE_FROM)
    db.commit()
    if seeded:
        print(f"Seeded {seeded} model_pricing_rates row(s)")


def downgrade(db: Session):
    if _table_exists(db, "usage_pending_buffer"):
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
            if _column_exists(db, "usage_pending_buffer", column):
                db.execute(
                    text(f"ALTER TABLE usage_pending_buffer DROP COLUMN {column}")
                )

    if _table_exists(db, "model_pricing_rates") and not _table_exists(
        db, "model_pricing_catalog"
    ):
        db.execute(
            text("ALTER TABLE model_pricing_rates RENAME TO model_pricing_catalog")
        )

    db.commit()
