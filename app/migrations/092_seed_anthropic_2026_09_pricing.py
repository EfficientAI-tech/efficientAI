"""Seed pricing rates for Anthropic models added in Sept 2026.

Adds claude-opus-5, claude-opus-5-5, claude-fable-5-1 and claude-mythos-5-1
to model_pricing_rates on existing installs (runtime pricing reads the table,
not models.json). Re-seeds every models.json entry, like 071.

Idempotent: upserts on (model, usage_kind, effective_from).
Usage recorded before this migration keeps zero cost until
``eai usage recompute --sync`` is run.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.usage.pricing import DEFAULT_RATES_EFFECTIVE_FROM, seed_pricing_rates

description = "Seed pricing rates for Claude Opus 5 / 5.5, Fable 5.1 and Mythos 5.1"

MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    exists = db.execute(
        text(
            "SELECT COALESCE(to_regclass('public.model_pricing_rates'), "
            "to_regclass('public.model_pricing_catalog'))"
        )
    ).scalar()
    if not exists:
        print("No pricing rates table found, skipping")
        return
    seeded = seed_pricing_rates(db, effective_from=DEFAULT_RATES_EFFECTIVE_FROM)
    db.commit()
    if seeded:
        print(f"Seeded {seeded} model pricing rate row(s)")


def downgrade(db: Session):
    pass
