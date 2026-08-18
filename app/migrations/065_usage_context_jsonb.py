"""Migration: JSONB context column for usage attribution metadata."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Move resource_id/resource_type into llm_usage_daily.context JSONB and "
    "recreate bucket uniqueness on context keys"
)

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


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


def _ensure_unique_bucket_index(db: Session) -> None:
    db.execute(text("DROP INDEX IF EXISTS uq_llm_usage_daily_bucket"))
    db.execute(
        text(
            f"""
            CREATE UNIQUE INDEX uq_llm_usage_daily_bucket
            ON llm_usage_daily (
                organization_id,
                COALESCE(workspace_id, '{_ZERO_UUID}'::uuid),
                product_section,
                model,
                usage_date,
                usage_kind,
                context
            )
            """
        )
    )


def _migrate_table_context(db: Session, table: str) -> None:
    if not _table_exists(db, table):
        return
    if not _column_exists(db, table, "context"):
        db.execute(
            text(
                f"""
                ALTER TABLE {table}
                ADD COLUMN context JSONB NOT NULL DEFAULT '{{}}'::jsonb
                """
            )
        )

    if _column_exists(db, table, "resource_id") or _column_exists(db, table, "resource_type"):
        db.execute(
            text(
                f"""
                UPDATE {table}
                SET context = COALESCE(context, '{{}}'::jsonb)
                    || CASE
                        WHEN resource_id IS NOT NULL THEN
                            jsonb_build_object('resource_id', resource_id::text)
                        ELSE '{{}}'::jsonb
                    END
                    || CASE
                        WHEN resource_type IS NOT NULL AND resource_type <> '' THEN
                            jsonb_build_object('resource_type', resource_type)
                        ELSE '{{}}'::jsonb
                    END
                WHERE resource_id IS NOT NULL
                   OR (resource_type IS NOT NULL AND resource_type <> '')
                """
            )
        )
        if _column_exists(db, table, "resource_id"):
            db.execute(text(f"DROP INDEX IF EXISTS ix_llm_usage_daily_org_resource_date"))
            db.execute(text(f"ALTER TABLE {table} DROP COLUMN resource_id"))
        if _column_exists(db, table, "resource_type"):
            db.execute(text(f"ALTER TABLE {table} DROP COLUMN resource_type"))


def upgrade(db: Session):
    if not _table_exists(db, "llm_usage_daily"):
        print("llm_usage_daily missing; run 062 first — skipping 065")
        db.commit()
        return

    _migrate_table_context(db, "llm_usage_daily")
    _migrate_table_context(db, "usage_pending_buffer")

    _ensure_unique_bucket_index(db)

    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_llm_usage_daily_context_gin
            ON llm_usage_daily USING gin (context)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_llm_usage_daily_context_resource_id
            ON llm_usage_daily ((context->>'resource_id'))
            WHERE context ? 'resource_id'
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_llm_usage_daily_context_call_import_id
            ON llm_usage_daily ((context->>'call_import_id'))
            WHERE context ? 'call_import_id'
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_llm_usage_daily_context_evaluation_id
            ON llm_usage_daily ((context->>'evaluation_id'))
            WHERE context ? 'evaluation_id'
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_llm_usage_daily_context_evaluation_row_id
            ON llm_usage_daily ((context->>'evaluation_row_id'))
            WHERE context ? 'evaluation_row_id'
            """
        )
    )
    print("Added context JSONB + migrated resource attribution")
    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "llm_usage_daily"):
        db.commit()
        return

    if not _column_exists(db, "llm_usage_daily", "resource_id"):
        db.execute(
            text(
                """
                ALTER TABLE llm_usage_daily
                ADD COLUMN resource_id UUID,
                ADD COLUMN resource_type VARCHAR(64)
                """
            )
        )
        db.execute(
            text(
                """
                UPDATE llm_usage_daily
                SET resource_id = NULLIF(context->>'resource_id', '')::uuid,
                    resource_type = NULLIF(context->>'resource_type', '')
                WHERE context IS NOT NULL
                """
            )
        )

    db.execute(text("DROP INDEX IF EXISTS ix_llm_usage_daily_context_evaluation_row_id"))
    db.execute(text("DROP INDEX IF EXISTS ix_llm_usage_daily_context_evaluation_id"))
    db.execute(text("DROP INDEX IF EXISTS ix_llm_usage_daily_context_call_import_id"))
    db.execute(text("DROP INDEX IF EXISTS ix_llm_usage_daily_context_resource_id"))
    db.execute(text("DROP INDEX IF EXISTS ix_llm_usage_daily_context_gin"))
    db.execute(text("DROP INDEX IF EXISTS uq_llm_usage_daily_bucket"))

    if _column_exists(db, "llm_usage_daily", "context"):
        db.execute(text("ALTER TABLE llm_usage_daily DROP COLUMN context"))

    db.execute(
        text(
            f"""
            CREATE UNIQUE INDEX uq_llm_usage_daily_bucket
            ON llm_usage_daily (
                organization_id,
                COALESCE(workspace_id, '{_ZERO_UUID}'::uuid),
                product_section,
                model,
                COALESCE(resource_id, '{_ZERO_UUID}'::uuid),
                usage_date,
                usage_kind
            )
            """
        )
    )
    db.commit()
