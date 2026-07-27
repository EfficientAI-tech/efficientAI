"""Catalog table size and row-count metrics for live call storage."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.orm import Session


_LIVE_CATALOG_TABLES = (
    "evaluator_results",
    "call_recordings",
)


def collect_catalog_storage_stats(db: Session) -> Dict[str, Any]:
    """Return row counts and approximate on-disk sizes for live catalog tables."""
    tables: Dict[str, Any] = {}
    for table_name in _LIVE_CATALOG_TABLES:
        row = db.execute(
            text(
                """
                SELECT
                    c.reltuples::bigint AS estimated_rows,
                    pg_total_relation_size(c.oid) AS total_bytes
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = :table_name
                  AND n.nspname = 'public'
                """
            ),
            {"table_name": table_name},
        ).mappings().first()

        exact_count = db.execute(
            text(f"SELECT COUNT(*) FROM {table_name}")
        ).scalar()

        tables[table_name] = {
            "row_count": int(exact_count or 0),
            "estimated_rows": int(row["estimated_rows"] or 0) if row else 0,
            "total_bytes": int(row["total_bytes"] or 0) if row else 0,
        }

    return {
        "tables": tables,
        "notes": (
            "Shard payload tables (evaluator_result_payloads, call_recording_payloads) "
            "live on data shards when sharding is enabled; sizes are per-shard."
        ),
    }
