"""Migration: Backfill llm_usage_daily.workspace_id from call-import attribution."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Backfill workspace_id on llm_usage_daily and usage_pending_buffer rows "
    "that have call-import context but were recorded with NULL workspace_id"
)

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"
_UUID_RE = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


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


def _dedupe_llm_usage_daily(db: Session) -> int:
    """Merge duplicate buckets after workspace backfill."""
    tts_col = (
        "SUM(COALESCE(tts_characters, 0))::bigint AS tts_characters,"
        if _column_exists(db, "llm_usage_daily", "tts_characters")
        else ""
    )
    tts_set = (
        "tts_characters = d.tts_characters,"
        if _column_exists(db, "llm_usage_daily", "tts_characters")
        else ""
    )

    db.execute(
        text(
            f"""
            WITH dupes AS (
                SELECT
                    organization_id,
                    COALESCE(workspace_id, '{_ZERO_UUID}'::uuid) AS ws_key,
                    product_section,
                    model,
                    usage_date,
                    COALESCE(usage_kind, 'llm') AS kind_key,
                    context,
                    MIN(id::text)::uuid AS keep_id,
                    SUM(prompt_tokens)::bigint AS prompt_tokens,
                    SUM(completion_tokens)::bigint AS completion_tokens,
                    SUM(cache_read_tokens)::bigint AS cache_read_tokens,
                    SUM(cache_creation_tokens)::bigint AS cache_creation_tokens,
                    SUM(reasoning_tokens)::bigint AS reasoning_tokens,
                    SUM(COALESCE(audio_seconds, 0))::bigint AS audio_seconds,
                    {tts_col}
                    SUM(call_count)::bigint AS call_count
                FROM llm_usage_daily
                GROUP BY 1, 2, 3, 4, 5, 6, 7
                HAVING COUNT(*) > 1
            )
            UPDATE llm_usage_daily AS u SET
                prompt_tokens = d.prompt_tokens,
                completion_tokens = d.completion_tokens,
                cache_read_tokens = d.cache_read_tokens,
                cache_creation_tokens = d.cache_creation_tokens,
                reasoning_tokens = d.reasoning_tokens,
                audio_seconds = d.audio_seconds,
                {tts_set}
                call_count = d.call_count,
                updated_at = now()
            FROM dupes AS d
            WHERE u.id = d.keep_id
            """
        )
    )

    result = db.execute(
        text(
            f"""
            WITH keepers AS (
                SELECT MIN(id::text)::uuid AS keep_id
                FROM llm_usage_daily
                GROUP BY
                    organization_id,
                    COALESCE(workspace_id, '{_ZERO_UUID}'::uuid),
                    product_section,
                    model,
                    usage_date,
                    COALESCE(usage_kind, 'llm'),
                    context
                HAVING COUNT(*) > 1
            )
            DELETE FROM llm_usage_daily AS u
            USING keepers AS k,
                  llm_usage_daily AS peer
            WHERE peer.id = k.keep_id
              AND u.id <> k.keep_id
              AND u.organization_id = peer.organization_id
              AND u.product_section = peer.product_section
              AND u.model = peer.model
              AND u.usage_date = peer.usage_date
              AND COALESCE(u.usage_kind, 'llm') = COALESCE(peer.usage_kind, 'llm')
              AND u.workspace_id IS NOT DISTINCT FROM peer.workspace_id
              AND u.context IS NOT DISTINCT FROM peer.context
            """
        )
    )
    return int(result.rowcount or 0)


def _backfill_table_workspace(db: Session, table: str) -> int:
    if not _table_exists(db, table):
        return 0
    if not _column_exists(db, table, "workspace_id"):
        return 0
    if not _column_exists(db, table, "context"):
        return 0

    total = 0

    # context.call_import_id
    result = db.execute(
        text(
            f"""
            UPDATE {table} AS u
            SET workspace_id = ci.workspace_id
            FROM call_imports AS ci
            WHERE u.workspace_id IS NULL
              AND u.context ? 'call_import_id'
              AND u.context->>'call_import_id' ~ :uuid_re
              AND ci.id = (u.context->>'call_import_id')::uuid
              AND ci.organization_id = u.organization_id
            """
        ),
        {"uuid_re": _UUID_RE},
    )
    total += int(result.rowcount or 0)

    # resource_type = call_import
    result = db.execute(
        text(
            f"""
            UPDATE {table} AS u
            SET workspace_id = ci.workspace_id
            FROM call_imports AS ci
            WHERE u.workspace_id IS NULL
              AND u.context->>'resource_type' = 'call_import'
              AND u.context->>'resource_id' ~ :uuid_re
              AND ci.id = (u.context->>'resource_id')::uuid
              AND ci.organization_id = u.organization_id
            """
        ),
        {"uuid_re": _UUID_RE},
    )
    total += int(result.rowcount or 0)

    # context.evaluation_id
    result = db.execute(
        text(
            f"""
            UPDATE {table} AS u
            SET workspace_id = e.workspace_id
            FROM call_import_evaluations AS e
            WHERE u.workspace_id IS NULL
              AND u.context ? 'evaluation_id'
              AND u.context->>'evaluation_id' ~ :uuid_re
              AND e.id = (u.context->>'evaluation_id')::uuid
              AND e.organization_id = u.organization_id
            """
        ),
        {"uuid_re": _UUID_RE},
    )
    total += int(result.rowcount or 0)

    # resource_type = call_import_evaluation
    result = db.execute(
        text(
            f"""
            UPDATE {table} AS u
            SET workspace_id = e.workspace_id
            FROM call_import_evaluations AS e
            WHERE u.workspace_id IS NULL
              AND u.context->>'resource_type' = 'call_import_evaluation'
              AND u.context->>'resource_id' ~ :uuid_re
              AND e.id = (u.context->>'resource_id')::uuid
              AND e.organization_id = u.organization_id
            """
        ),
        {"uuid_re": _UUID_RE},
    )
    total += int(result.rowcount or 0)

    # context.call_import_row_id
    result = db.execute(
        text(
            f"""
            UPDATE {table} AS u
            SET workspace_id = cir.workspace_id
            FROM call_import_rows AS cir
            WHERE u.workspace_id IS NULL
              AND u.context ? 'call_import_row_id'
              AND u.context->>'call_import_row_id' ~ :uuid_re
              AND cir.id = (u.context->>'call_import_row_id')::uuid
              AND cir.organization_id = u.organization_id
            """
        ),
        {"uuid_re": _UUID_RE},
    )
    total += int(result.rowcount or 0)

    # context.evaluation_row_id
    result = db.execute(
        text(
            f"""
            UPDATE {table} AS u
            SET workspace_id = e.workspace_id
            FROM call_import_evaluation_rows AS er
            JOIN call_import_evaluations AS e ON e.id = er.evaluation_id
            WHERE u.workspace_id IS NULL
              AND u.context ? 'evaluation_row_id'
              AND u.context->>'evaluation_row_id' ~ :uuid_re
              AND er.id = (u.context->>'evaluation_row_id')::uuid
              AND e.organization_id = u.organization_id
            """
        ),
        {"uuid_re": _UUID_RE},
    )
    total += int(result.rowcount or 0)

    return total


def upgrade(db: Session):
    if not _table_exists(db, "llm_usage_daily"):
        print("llm_usage_daily missing; skipping 066")
        db.commit()
        return

    daily_updated = _backfill_table_workspace(db, "llm_usage_daily")
    print(f"Backfilled workspace_id on {daily_updated} llm_usage_daily row(s)")

    removed = _dedupe_llm_usage_daily(db)
    if removed:
        print(f"Removed {removed} duplicate llm_usage_daily row(s) after merge")

    buffer_updated = _backfill_table_workspace(db, "usage_pending_buffer")
    if buffer_updated:
        print(
            f"Backfilled workspace_id on {buffer_updated} usage_pending_buffer row(s)"
        )

    db.commit()


def downgrade(db: Session):
    # No-op: cannot distinguish backfilled workspace_id from originally recorded values.
    db.commit()
