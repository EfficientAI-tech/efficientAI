"""Migration: Reconcile llm_usage_daily bucket unique index with full JSONB context."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Merge legacy resource-scoped usage buckets and recreate uq_llm_usage_daily_bucket "
    "on full context JSONB (per-row attribution)"
)

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


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


def _dedupe_by_context_resource_keys(db: Session) -> int:
    """Merge rows that share context resource_id/resource_type (legacy unique index)."""
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
                    COALESCE(context->>'resource_id', '') AS res_id_key,
                    COALESCE(context->>'resource_type', '') AS res_type_key,
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
                GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
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
                    COALESCE(context->>'resource_id', ''),
                    COALESCE(context->>'resource_type', '')
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
              AND COALESCE(u.context->>'resource_id', '') =
                  COALESCE(peer.context->>'resource_id', '')
              AND COALESCE(u.context->>'resource_type', '') =
                  COALESCE(peer.context->>'resource_type', '')
            """
        )
    )
    return int(result.rowcount or 0)


def _dedupe_by_full_context(db: Session) -> int:
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


def _ensure_context_bucket_index(db: Session) -> None:
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


def upgrade(db: Session):
    if not _table_exists(db, "llm_usage_daily"):
        print("llm_usage_daily missing; skipping 067")
        db.commit()
        return
    if not _column_exists(db, "llm_usage_daily", "context"):
        print("llm_usage_daily.context missing; run 065 first — skipping 067")
        db.commit()
        return

    legacy_removed = _dedupe_by_context_resource_keys(db)
    if legacy_removed:
        print(f"Merged {legacy_removed} legacy resource-scoped duplicate row(s)")

    context_removed = _dedupe_by_full_context(db)
    if context_removed:
        print(f"Merged {context_removed} duplicate full-context row(s)")

    _ensure_context_bucket_index(db)
    print("Recreated uq_llm_usage_daily_bucket on full context JSONB")
    db.commit()


def downgrade(db: Session):
    db.commit()
