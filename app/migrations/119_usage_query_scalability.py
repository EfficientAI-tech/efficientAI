"""Backfill call-import context keys and add rollup indexes for usage reads."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Backfill llm_usage_daily call_import_id/evaluation_id and add read indexes"
)
MIGRATION_SCOPE = "catalog"

_UUID_RE = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def _table_exists(db: Session, table: str) -> bool:
    return (
        db.execute(
            text(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :table_name
                """
            ),
            {"table_name": table},
        ).first()
        is not None
    )


def _backfill_context_keys(db: Session) -> None:
    db.execute(
        text(
            """
            UPDATE llm_usage_daily
            SET context = context || jsonb_build_object(
                'call_import_id', context->>'resource_id'
            )
            WHERE context->>'resource_type' = 'call_import'
              AND NOT (context ? 'call_import_id')
              AND COALESCE(context->>'resource_id', '') <> ''
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE llm_usage_daily
            SET context = context || jsonb_build_object(
                'evaluation_id', context->>'resource_id'
            )
            WHERE context->>'resource_type' = 'call_import_evaluation'
              AND NOT (context ? 'evaluation_id')
              AND COALESCE(context->>'resource_id', '') <> ''
            """
        )
    )
    if _table_exists(db, "call_import_evaluations"):
        db.execute(
            text(
                """
                UPDATE llm_usage_daily AS u
                SET context = u.context || jsonb_build_object(
                    'call_import_id', e.call_import_id::text
                )
                FROM call_import_evaluations AS e
                WHERE NOT (u.context ? 'call_import_id')
                  AND u.context ? 'evaluation_id'
                  AND u.context->>'evaluation_id' ~ :uuid_re
                  AND e.id = (u.context->>'evaluation_id')::uuid
                  AND e.organization_id = u.organization_id
                """
            ),
            {"uuid_re": _UUID_RE},
        )
    if _table_exists(db, "call_import_rows") and _table_exists(db, "call_imports"):
        db.execute(
            text(
                """
                UPDATE llm_usage_daily AS u
                SET context = u.context || jsonb_build_object(
                    'call_import_id', ci.id::text
                )
                FROM call_import_rows AS cir
                JOIN call_imports AS ci ON ci.id = cir.call_import_id
                WHERE NOT (u.context ? 'call_import_id')
                  AND u.context ? 'call_import_row_id'
                  AND u.context->>'call_import_row_id' ~ :uuid_re
                  AND cir.id = (u.context->>'call_import_row_id')::uuid
                  AND ci.organization_id = u.organization_id
                """
            ),
            {"uuid_re": _UUID_RE},
        )
    if _table_exists(db, "call_import_evaluation_rows") and _table_exists(
        db, "call_import_evaluations"
    ):
        db.execute(
            text(
                """
                UPDATE llm_usage_daily AS u
                SET context = u.context
                    || jsonb_build_object('evaluation_id', e.id::text)
                    || jsonb_build_object('call_import_id', e.call_import_id::text)
                FROM call_import_evaluation_rows AS er
                JOIN call_import_evaluations AS e ON e.id = er.evaluation_id
                WHERE u.context ? 'evaluation_row_id'
                  AND u.context->>'evaluation_row_id' ~ :uuid_re
                  AND er.id = (u.context->>'evaluation_row_id')::uuid
                  AND e.organization_id = u.organization_id
                  AND (
                    NOT (u.context ? 'evaluation_id')
                    OR NOT (u.context ? 'call_import_id')
                  )
                """
            ),
            {"uuid_re": _UUID_RE},
        )


def _ensure_indexes(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_llm_usage_daily_org_updated_at
            ON llm_usage_daily (organization_id, updated_at DESC)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_llm_usage_daily_org_section_date
            ON llm_usage_daily (organization_id, product_section, usage_date)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_llm_usage_daily_org_model_date
            ON llm_usage_daily (organization_id, model, usage_date)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_llm_usage_daily_org_date_call_import
            ON llm_usage_daily (
                organization_id,
                usage_date,
                (context->>'call_import_id')
            )
            WHERE context ? 'call_import_id'
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_llm_usage_daily_org_date_evaluation
            ON llm_usage_daily (
                organization_id,
                usage_date,
                (context->>'evaluation_id')
            )
            WHERE context ? 'evaluation_id'
            """
        )
    )


def upgrade(db: Session):
    if not _table_exists(db, "llm_usage_daily"):
        print("llm_usage_daily missing; skipping 119")
        db.commit()
        return
    from app.services.usage.rollup_maintenance import (
        backfill_usage_context_keys,
        ensure_usage_read_indexes,
        repair_orphaned_row_context,
    )

    backfill_usage_context_keys(db)
    repair_orphaned_row_context(db)
    ensure_usage_read_indexes(db)
    print("Backfilled usage context keys and ensured usage read indexes")


def downgrade(db: Session):
    if not _table_exists(db, "llm_usage_daily"):
        db.commit()
        return
    for index in (
        "ix_llm_usage_daily_org_updated_at",
        "ix_llm_usage_daily_org_section_date",
        "ix_llm_usage_daily_org_model_date",
        "ix_llm_usage_daily_org_date_call_import",
        "ix_llm_usage_daily_org_date_evaluation",
    ):
        db.execute(text(f"DROP INDEX IF EXISTS {index}"))
    db.commit()
