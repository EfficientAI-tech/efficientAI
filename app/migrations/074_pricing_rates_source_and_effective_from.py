"""Migration: widen pricing source column and normalize effective_from baseline."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.usage.pricing import DEFAULT_RATES_EFFECTIVE_FROM, seed_pricing_rates

description = (
    "Widen model_pricing_rates.source to VARCHAR(255) and normalize effective_from "
    "to 2020-01-01 baseline"
)

_BASELINE = DEFAULT_RATES_EFFECTIVE_FROM.isoformat()


def _table_exists(db: Session, table: str) -> bool:
    return (
        db.execute(
            text("SELECT to_regclass(:table_name)"),
            {"table_name": f"public.{table}"},
        ).scalar()
        is not None
    )


def upgrade(db: Session) -> None:
    table = "model_pricing_rates"
    if not _table_exists(db, table):
        table = "model_pricing_catalog"
    if not _table_exists(db, table):
        print("No pricing rates table found, skipping")
        return

    db.execute(
        text(
            f"""
            ALTER TABLE {table}
            ALTER COLUMN source TYPE VARCHAR(255)
            """
        )
    )
    print(f"Widened {table}.source to VARCHAR(255)")

    db.execute(
        text(
            f"""
            DELETE FROM {table} newer
            USING {table} baseline
            WHERE newer.model = baseline.model
              AND newer.usage_kind = baseline.usage_kind
              AND newer.effective_from > CAST(:baseline AS date)
              AND baseline.effective_from = CAST(:baseline AS date)
            """
        ),
        {"baseline": _BASELINE},
    )
    db.execute(
        text(
            f"""
            UPDATE {table}
            SET effective_from = CAST(:baseline AS date)
            WHERE effective_from > CAST(:baseline AS date)
            """
        ),
        {"baseline": _BASELINE},
    )
    print(f"Normalized {table} effective_from to {_BASELINE}")

    seeded = seed_pricing_rates(db, effective_from=DEFAULT_RATES_EFFECTIVE_FROM)
    from app.services.usage.pricing_cache import invalidate_all_pricing_cache

    invalidate_all_pricing_cache()
    db.commit()
    if seeded:
        print(f"Re-seeded {seeded} pricing rate row(s) at {_BASELINE}")


def downgrade(db: Session) -> None:
    pass
