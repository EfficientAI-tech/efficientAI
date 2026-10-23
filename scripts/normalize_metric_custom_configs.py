#!/usr/bin/env python3
"""Rewrite enum/classification custom_config option shapes in the database.

Dry-run by default; pass --apply to commit. Safe to run on sandbox/prod
after deploying option_labels coercion logic.
"""

from __future__ import annotations

import argparse

from app.database import SessionLocal
from app.models.database import Metric
from app.services.metrics.option_labels import coerce_custom_config_for_storage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist normalized custom_config rows (default: dry-run only).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    updated = 0
    scanned = 0
    try:
        rows = (
            db.query(Metric)
            .filter(Metric.custom_data_type.in_(["enum", "classification"]))
            .all()
        )
        for metric in rows:
            scanned += 1
            coerced = coerce_custom_config_for_storage(
                metric.custom_data_type, metric.custom_config
            )
            if coerced == metric.custom_config:
                continue
            updated += 1
            print(f"  {metric.id} {metric.name!r} ({metric.custom_data_type})")
            if args.apply:
                metric.custom_config = coerced
        if args.apply and updated:
            db.commit()
            print(f"Committed {updated} metric(s).")
        else:
            print(f"Would update {updated} of {scanned} enum/classification metric(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
