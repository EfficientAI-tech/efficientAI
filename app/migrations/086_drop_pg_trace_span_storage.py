"""Drop legacy Postgres trace/span storage (control plane only; traces served from ClickHouse)."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Drop PG synthetic trace tables; keep evaluator_results.synthetic_call_trace_id as opaque UUID"

MIGRATION_SCOPE = "catalog"


def _table_exists(db: Session, table_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    )
    return bool(result.scalar())


def _fk_exists(db: Session, table_name: str, constraint_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = :table_name
                  AND constraint_name = :constraint_name
                  AND constraint_type = 'FOREIGN KEY'
            )
            """
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    )
    return bool(result.scalar())


def upgrade(db: Session) -> None:
    if _fk_exists(db, "evaluator_results", "evaluator_results_synthetic_call_trace_id_fkey"):
        db.execute(
            text(
                "ALTER TABLE evaluator_results "
                "DROP CONSTRAINT evaluator_results_synthetic_call_trace_id_fkey"
            )
        )

    for table in (
        "synthetic_trace_ingest_staging",
        "synthetic_trace_span_batches",
        "synthetic_trace_payloads",
        "synthetic_trace_otel_payloads",
        "synthetic_call_traces",
    ):
        if _table_exists(db, table):
            db.execute(text(f"DROP TABLE {table} CASCADE"))

    db.commit()
