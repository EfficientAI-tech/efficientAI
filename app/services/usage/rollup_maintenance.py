"""Collision-safe usage-context backfill and non-blocking read indexes."""

from __future__ import annotations

import json
from typing import Iterable, Sequence

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

_UUID_RE = (
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    "[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_BATCH = 1000

_METRIC_ADD = """
    prompt_tokens = keeper.prompt_tokens + src.prompt_tokens,
    completion_tokens = keeper.completion_tokens + src.completion_tokens,
    cache_read_tokens = keeper.cache_read_tokens + src.cache_read_tokens,
    cache_creation_tokens = keeper.cache_creation_tokens + src.cache_creation_tokens,
    reasoning_tokens = keeper.reasoning_tokens + src.reasoning_tokens,
    audio_seconds = keeper.audio_seconds + src.audio_seconds,
    tts_characters = keeper.tts_characters + src.tts_characters,
    call_count = keeper.call_count + src.call_count,
    input_cost_micro_usd = keeper.input_cost_micro_usd + src.input_cost_micro_usd,
    output_cost_micro_usd = keeper.output_cost_micro_usd + src.output_cost_micro_usd,
    cache_read_cost_micro_usd = keeper.cache_read_cost_micro_usd + src.cache_read_cost_micro_usd,
    cache_creation_cost_micro_usd = keeper.cache_creation_cost_micro_usd + src.cache_creation_cost_micro_usd,
    reasoning_cost_micro_usd = keeper.reasoning_cost_micro_usd + src.reasoning_cost_micro_usd,
    audio_cost_micro_usd = keeper.audio_cost_micro_usd + src.audio_cost_micro_usd,
    tts_cost_micro_usd = keeper.tts_cost_micro_usd + src.tts_cost_micro_usd,
    total_cost_micro_usd = keeper.total_cost_micro_usd + src.total_cost_micro_usd,
    updated_at = now()
"""

_SAME_BUCKET = """
    keeper.organization_id = src.organization_id
    AND keeper.product_section = src.product_section
    AND keeper.model = src.model
    AND keeper.usage_date = src.usage_date
    AND COALESCE(keeper.usage_kind, 'llm') = COALESCE(src.usage_kind, 'llm')
    AND keeper.workspace_id IS NOT DISTINCT FROM src.workspace_id
"""

_READ_INDEXES = (
    """
    CREATE INDEX {mode} IF NOT EXISTS ix_llm_usage_daily_org_updated_at
    ON llm_usage_daily (organization_id, updated_at DESC)
    """,
    """
    CREATE INDEX {mode} IF NOT EXISTS ix_llm_usage_daily_org_section_date
    ON llm_usage_daily (organization_id, product_section, usage_date)
    """,
    """
    CREATE INDEX {mode} IF NOT EXISTS ix_llm_usage_daily_org_model_date
    ON llm_usage_daily (organization_id, model, usage_date)
    """,
    """
    CREATE INDEX {mode} IF NOT EXISTS ix_llm_usage_daily_org_date_call_import
    ON llm_usage_daily (organization_id, usage_date, (context->>'call_import_id'))
    WHERE context ? 'call_import_id'
    """,
    """
    CREATE INDEX {mode} IF NOT EXISTS ix_llm_usage_daily_org_date_evaluation
    ON llm_usage_daily (organization_id, usage_date, (context->>'evaluation_id'))
    WHERE context ? 'evaluation_id'
    """,
    """
    CREATE INDEX {mode} IF NOT EXISTS ix_llm_usage_daily_org_date_resource
    ON llm_usage_daily (organization_id, usage_date, (context->>'resource_id'))
    WHERE context ? 'resource_id'
    """,
)


def _ensure_patch_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TEMP TABLE IF NOT EXISTS usage_ctx_patch (
                src_id uuid PRIMARY KEY,
                new_context jsonb NOT NULL
            ) ON COMMIT DROP
            """
        )
    )
    db.execute(text("TRUNCATE usage_ctx_patch"))


def merge_staged_usage_context(db: Session) -> None:
    """Fold staged context rewrites into existing buckets, then apply the rest.

    ``uq_llm_usage_daily_bucket`` includes ``context``, so two rows must not be
    updated onto the same key.
    """
    db.execute(
        text(
            f"""
            UPDATE llm_usage_daily AS keeper
            SET {_METRIC_ADD}
            FROM usage_ctx_patch AS patch
            JOIN llm_usage_daily AS src ON src.id = patch.src_id
            WHERE {_SAME_BUCKET}
              AND keeper.context = patch.new_context
              AND keeper.id <> src.id
            """
        )
    )
    db.execute(
        text(
            f"""
            DELETE FROM llm_usage_daily AS src
            USING usage_ctx_patch AS patch, llm_usage_daily AS keeper
            WHERE src.id = patch.src_id
              AND {_SAME_BUCKET}
              AND keeper.context = patch.new_context
              AND keeper.id <> src.id
            """
        )
    )
    db.execute(
        text(
            f"""
            UPDATE llm_usage_daily AS keeper
            SET {_METRIC_ADD}
            FROM usage_ctx_patch AS keep_patch
            JOIN usage_ctx_patch AS drop_patch
              ON drop_patch.new_context = keep_patch.new_context
             AND drop_patch.src_id > keep_patch.src_id
            JOIN llm_usage_daily AS src ON src.id = drop_patch.src_id
            JOIN llm_usage_daily AS src_keep ON src_keep.id = keep_patch.src_id
            WHERE keeper.id = keep_patch.src_id
              AND src.organization_id = src_keep.organization_id
              AND src.product_section = src_keep.product_section
              AND src.model = src_keep.model
              AND src.usage_date = src_keep.usage_date
              AND COALESCE(src.usage_kind, 'llm') = COALESCE(src_keep.usage_kind, 'llm')
              AND src.workspace_id IS NOT DISTINCT FROM src_keep.workspace_id
            """
        )
    )
    db.execute(
        text(
            """
            DELETE FROM llm_usage_daily AS src
            USING usage_ctx_patch AS keep_patch,
                  usage_ctx_patch AS drop_patch,
                  llm_usage_daily AS src_keep
            WHERE src.id = drop_patch.src_id
              AND src_keep.id = keep_patch.src_id
              AND drop_patch.new_context = keep_patch.new_context
              AND drop_patch.src_id > keep_patch.src_id
              AND src.organization_id = src_keep.organization_id
              AND src.product_section = src_keep.product_section
              AND src.model = src_keep.model
              AND src.usage_date = src_keep.usage_date
              AND COALESCE(src.usage_kind, 'llm') = COALESCE(src_keep.usage_kind, 'llm')
              AND src.workspace_id IS NOT DISTINCT FROM src_keep.workspace_id
            """
        )
    )
    db.execute(
        text(
            """
            DELETE FROM usage_ctx_patch AS drop_patch
            USING usage_ctx_patch AS keep_patch
            WHERE drop_patch.new_context = keep_patch.new_context
              AND drop_patch.src_id > keep_patch.src_id
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE llm_usage_daily AS src
            SET context = patch.new_context,
                updated_at = now()
            FROM usage_ctx_patch AS patch
            WHERE src.id = patch.src_id
            """
        )
    )


def stage_context_select(db: Session, select_sql: str, params: dict | None = None) -> None:
    _ensure_patch_table(db)
    db.execute(
        text(
            f"INSERT INTO usage_ctx_patch (src_id, new_context) {select_sql}"
        ),
        params or {},
    )
    merge_staged_usage_context(db)


def stage_context_pairs(db: Session, pairs: Sequence[tuple[str, dict]]) -> None:
    if not pairs:
        return
    _ensure_patch_table(db)
    payload = [
        {"src_id": src_id, "new_context": context}
        for src_id, context in pairs
    ]
    db.execute(
        text(
            """
            INSERT INTO usage_ctx_patch (src_id, new_context)
            SELECT CAST(x.src_id AS uuid), x.new_context
            FROM jsonb_to_recordset(CAST(:rows AS jsonb))
                AS x(src_id text, new_context jsonb)
            ON CONFLICT (src_id) DO UPDATE
                SET new_context = EXCLUDED.new_context
            """
        ),
        {"rows": json.dumps(payload)},
    )
    merge_staged_usage_context(db)


def backfill_usage_context_keys(db: Session) -> None:
    """Stamp call_import_id / evaluation_id without colliding on the bucket index."""
    stage_context_select(
        db,
        """
        SELECT u.id,
               u.context || jsonb_build_object(
                   'call_import_id', u.context->>'resource_id'
               )
        FROM llm_usage_daily AS u
        WHERE u.context->>'resource_type' = 'call_import'
          AND NOT (u.context ? 'call_import_id')
          AND COALESCE(u.context->>'resource_id', '') <> ''
        """,
    )
    stage_context_select(
        db,
        """
        SELECT u.id,
               u.context || jsonb_build_object(
                   'evaluation_id', u.context->>'resource_id'
               )
        FROM llm_usage_daily AS u
        WHERE u.context->>'resource_type' = 'call_import_evaluation'
          AND NOT (u.context ? 'evaluation_id')
          AND COALESCE(u.context->>'resource_id', '') <> ''
        """,
    )
    stage_context_select(
        db,
        """
        SELECT u.id,
               u.context || jsonb_build_object(
                   'call_import_id', e.call_import_id::text
               )
        FROM llm_usage_daily AS u
        JOIN call_import_evaluations AS e
          ON e.organization_id = u.organization_id
         AND e.id = (u.context->>'evaluation_id')::uuid
        WHERE NOT (u.context ? 'call_import_id')
          AND u.context ? 'evaluation_id'
          AND u.context->>'evaluation_id' ~ :uuid_re
        """,
        {"uuid_re": _UUID_RE},
    )


def _chunks(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _text_ids(db: Session, sql: str) -> list[str]:
    rows = db.execute(text(sql), {"uuid_re": _UUID_RE, "limit": 5000}).all()
    return [str(row[0]) for row in rows if row[0]]


def repair_orphaned_row_context(db: Session) -> None:
    """Resolve row ids that still live only on shards into catalog context keys."""
    from app.db_sharding.pool_manager import db_pool_manager

    import_row_ids = _text_ids(
        db,
        """
        SELECT DISTINCT context->>'call_import_row_id'
        FROM llm_usage_daily
        WHERE context ? 'call_import_row_id'
          AND NOT (context ? 'call_import_id')
          AND context->>'call_import_row_id' ~ :uuid_re
        LIMIT :limit
        """,
    )
    eval_row_ids = _text_ids(
        db,
        """
        SELECT DISTINCT context->>'evaluation_row_id'
        FROM llm_usage_daily
        WHERE context ? 'evaluation_row_id'
          AND (
            NOT (context ? 'evaluation_id')
            OR NOT (context ? 'call_import_id')
          )
          AND context->>'evaluation_row_id' ~ :uuid_re
        LIMIT :limit
        """,
    )
    if not import_row_ids and not eval_row_ids:
        return
    if not (db_pool_manager.sharding_enabled and db_pool_manager.router):
        return

    import_by_row: dict[str, str] = {}
    eval_by_row: dict[str, str] = {}
    for shard_id in db_pool_manager.router.shard_ids:
        session = db_pool_manager.shard_session_factory(shard_id)()
        try:
            for batch in _chunks(import_row_ids, _BATCH):
                found = session.execute(
                    text(
                        """
                        SELECT id::text, call_import_id::text
                        FROM call_import_rows
                        WHERE id::text = ANY(:ids)
                        """
                    ),
                    {"ids": list(batch)},
                ).all()
                import_by_row.update({row[0]: row[1] for row in found if row[0] and row[1]})
            for batch in _chunks(eval_row_ids, _BATCH):
                found = session.execute(
                    text(
                        """
                        SELECT id::text, evaluation_id::text
                        FROM call_import_evaluation_rows
                        WHERE id::text = ANY(:ids)
                        """
                    ),
                    {"ids": list(batch)},
                ).all()
                eval_by_row.update({row[0]: row[1] for row in found if row[0] and row[1]})
        finally:
            session.close()

    eval_to_import: dict[str, str] = {}
    eval_ids = list({value for value in eval_by_row.values() if value})
    for batch in _chunks(eval_ids, _BATCH):
        found = db.execute(
            text(
                """
                SELECT id::text, call_import_id::text
                FROM call_import_evaluations
                WHERE id::text = ANY(:ids)
                """
            ),
            {"ids": list(batch)},
        ).all()
        eval_to_import.update({row[0]: row[1] for row in found if row[0] and row[1]})

    if import_by_row:
        rows = db.execute(
            text(
                """
                SELECT id::text, context
                FROM llm_usage_daily
                WHERE context ? 'call_import_row_id'
                  AND NOT (context ? 'call_import_id')
                  AND context->>'call_import_row_id' = ANY(:ids)
                """
            ),
            {"ids": list(import_by_row)},
        ).all()
        pairs = []
        for src_id, context in rows:
            ctx = dict(context or {})
            import_id = import_by_row.get(str(ctx.get("call_import_row_id") or ""))
            if not import_id:
                continue
            ctx["call_import_id"] = import_id
            pairs.append((str(src_id), ctx))
        stage_context_pairs(db, pairs)

    if eval_by_row:
        rows = db.execute(
            text(
                """
                SELECT id::text, context
                FROM llm_usage_daily
                WHERE context ? 'evaluation_row_id'
                  AND context->>'evaluation_row_id' = ANY(:ids)
                """
            ),
            {"ids": list(eval_by_row)},
        ).all()
        pairs = []
        for src_id, context in rows:
            ctx = dict(context or {})
            eval_id = eval_by_row.get(str(ctx.get("evaluation_row_id") or ""))
            if not eval_id:
                continue
            ctx.setdefault("evaluation_id", eval_id)
            import_id = eval_to_import.get(eval_id)
            if import_id:
                ctx.setdefault("call_import_id", import_id)
            pairs.append((str(src_id), ctx))
        stage_context_pairs(db, pairs)


def ensure_usage_read_indexes(db: Session) -> None:
    """Build read indexes without holding the migration transaction open."""
    bind = db.get_bind()
    db.commit()
    if bind is not None and bind.dialect.name == "postgresql":
        try:
            with bind.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                for statement in _READ_INDEXES:
                    conn.execute(text(statement.format(mode="CONCURRENTLY")))
            return
        except Exception as exc:
            logger.warning("concurrent usage index build fell back: {}", exc)
    for statement in _READ_INDEXES:
        db.execute(text(statement.format(mode="")))
    db.commit()
