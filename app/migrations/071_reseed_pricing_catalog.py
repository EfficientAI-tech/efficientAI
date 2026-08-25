"""Migration: re-seed model_pricing_rates from models.json after effective_from fix."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.usage.pricing import DEFAULT_RATES_EFFECTIVE_FROM, seed_pricing_rates

description = "Re-seed model_pricing_rates from models.json pricing blocks"


def upgrade(db: Session):
    table = "model_pricing_rates"
    exists = db.execute(
        text("SELECT to_regclass('public.model_pricing_rates')")
    ).scalar()
    if not exists:
        table = "model_pricing_catalog"
    db.execute(
        text(
            f"""
            UPDATE {table}
            SET effective_from = CAST(:effective_from AS date)
            WHERE effective_from > CAST(:effective_from AS date)
            """
        ),
        {"effective_from": DEFAULT_RATES_EFFECTIVE_FROM.isoformat()},
    )
    seeded = seed_pricing_rates(db, effective_from=DEFAULT_RATES_EFFECTIVE_FROM)
    db.commit()
    if seeded:
        print(f"Re-seeded {seeded} model pricing rate row(s)")


def downgrade(db: Session):
    pass
