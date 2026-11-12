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
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"
_BATCH = 1000
_ORPHAN_BATCH_LIMIT = 5000

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

READ_INDEX_NAMES = (
    "ix_llm_usage_daily_org_updated_at",
    "ix_llm_usage_daily_org_section_date",
    "ix_llm_usage_daily_org_model_date",
    "ix_llm_usage_daily_org_date_call_import",
    "ix_llm_usage_daily_org_date_evaluation",
    "ix_llm_usage_daily_org_date_resource",
)


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
    """Fold staged context rewrites into target buckets without losing rows or counts.

    ``uq_llm_usage_daily_bucket`` is keyed on
    ``(organization_id, COALESCE(workspace_id, zero_uuid), product_section,
    model, usage_date, usage_kind, context)``. Multiple staged rows may map onto
    the same target bucket or onto an already-populated keeper row, while rows
    on *different* dates/models that happen to share ``new_context`` remain
    independent buckets and must all be updated.
    """
    # Step 1: Fold any staged source rows into an already-existing keeper row
    # that shares the exact full 7-tuple bucket key (pre-aggregating SUMs so
    # 2+ staged rows hitting the same keeper never lose counts).
    db.execute(
        text(
            """
            WITH colliding AS (
                SELECT
                    keeper.id AS keeper_id,
                    src.id AS src_id,
                    src.prompt_tokens,
                    src.completion_tokens,
                    src.cache_read_tokens,
                    src.cache_creation_tokens,
                    src.reasoning_tokens,
                    src.audio_seconds,
                    src.tts_characters,
                    src.call_count,
                    src.input_cost_micro_usd,
                    src.output_cost_micro_usd,
                    src.cache_read_cost_micro_usd,
                    src.cache_creation_cost_micro_usd,
                    src.reasoning_cost_micro_usd,
                    src.audio_cost_micro_usd,
                    src.tts_cost_micro_usd,
                    src.total_cost_micro_usd
                FROM usage_ctx_patch AS patch
                JOIN llm_usage_daily AS src ON src.id = patch.src_id
                JOIN llm_usage_daily AS keeper
                  ON keeper.organization_id = src.organization_id
                 AND keeper.product_section = src.product_section
                 AND keeper.model = src.model
                 AND keeper.usage_date = src.usage_date
                 AND COALESCE(keeper.usage_kind, 'llm') = COALESCE(src.usage_kind, 'llm')
                 AND keeper.workspace_id IS NOT DISTINCT FROM src.workspace_id
                 AND keeper.context = patch.new_context
                 AND keeper.id <> src.id
            ),
            keeper_deltas AS (
                SELECT
                    keeper_id,
                    SUM(prompt_tokens)::bigint AS prompt_tokens,
                    SUM(completion_tokens)::bigint AS completion_tokens,
                    SUM(cache_read_tokens)::bigint AS cache_read_tokens,
                    SUM(cache_creation_tokens)::bigint AS cache_creation_tokens,
                    SUM(reasoning_tokens)::bigint AS reasoning_tokens,
                    SUM(audio_seconds)::bigint AS audio_seconds,
                    SUM(tts_characters)::bigint AS tts_characters,
                    SUM(call_count)::bigint AS call_count,
                    SUM(input_cost_micro_usd)::bigint AS input_cost_micro_usd,
                    SUM(output_cost_micro_usd)::bigint AS output_cost_micro_usd,
                    SUM(cache_read_cost_micro_usd)::bigint AS cache_read_cost_micro_usd,
                    SUM(cache_creation_cost_micro_usd)::bigint AS cache_creation_cost_micro_usd,
                    SUM(reasoning_cost_micro_usd)::bigint AS reasoning_cost_micro_usd,
                    SUM(audio_cost_micro_usd)::bigint AS audio_cost_micro_usd,
                    SUM(tts_cost_micro_usd)::bigint AS tts_cost_micro_usd,
                    SUM(total_cost_micro_usd)::bigint AS total_cost_micro_usd
                FROM colliding
                GROUP BY keeper_id
            ),
            updated_keepers AS (
                UPDATE llm_usage_daily AS keeper
                SET prompt_tokens = keeper.prompt_tokens + d.prompt_tokens,
                    completion_tokens = keeper.completion_tokens + d.completion_tokens,
                    cache_read_tokens = keeper.cache_read_tokens + d.cache_read_tokens,
                    cache_creation_tokens = keeper.cache_creation_tokens + d.cache_creation_tokens,
                    reasoning_tokens = keeper.reasoning_tokens + d.reasoning_tokens,
                    audio_seconds = keeper.audio_seconds + d.audio_seconds,
                    tts_characters = keeper.tts_characters + d.tts_characters,
                    call_count = keeper.call_count + d.call_count,
                    input_cost_micro_usd = keeper.input_cost_micro_usd + d.input_cost_micro_usd,
                    output_cost_micro_usd = keeper.output_cost_micro_usd + d.output_cost_micro_usd,
                    cache_read_cost_micro_usd = keeper.cache_read_cost_micro_usd + d.cache_read_cost_micro_usd,
                    cache_creation_cost_micro_usd = keeper.cache_creation_cost_micro_usd + d.cache_creation_cost_micro_usd,
                    reasoning_cost_micro_usd = keeper.reasoning_cost_micro_usd + d.reasoning_cost_micro_usd,
                    audio_cost_micro_usd = keeper.audio_cost_micro_usd + d.audio_cost_micro_usd,
                    tts_cost_micro_usd = keeper.tts_cost_micro_usd + d.tts_cost_micro_usd,
                    total_cost_micro_usd = keeper.total_cost_micro_usd + d.total_cost_micro_usd,
                    updated_at = now()
                FROM keeper_deltas AS d
                WHERE keeper.id = d.keeper_id
                RETURNING keeper.id
            ),
            deleted_src AS (
                DELETE FROM llm_usage_daily AS src
                USING colliding AS c
                WHERE src.id = c.src_id
                RETURNING src.id
            )
            DELETE FROM usage_ctx_patch AS patch
            USING deleted_src AS d
            WHERE patch.src_id = d.id
            """
        )
    )

    # Step 2: Among remaining staged rows, merge any rows that collide with
    # *each other* on the full 7-tuple bucket key into MIN(id::text)::uuid.
    db.execute(
        text(
            f"""
            WITH patch_groups AS (
                SELECT
                    MIN(src.id::text)::uuid AS keep_id,
                    SUM(src.prompt_tokens)::bigint AS prompt_tokens,
                    SUM(src.completion_tokens)::bigint AS completion_tokens,
                    SUM(src.cache_read_tokens)::bigint AS cache_read_tokens,
                    SUM(src.cache_creation_tokens)::bigint AS cache_creation_tokens,
                    SUM(src.reasoning_tokens)::bigint AS reasoning_tokens,
                    SUM(src.audio_seconds)::bigint AS audio_seconds,
                    SUM(src.tts_characters)::bigint AS tts_characters,
                    SUM(src.call_count)::bigint AS call_count,
                    SUM(src.input_cost_micro_usd)::bigint AS input_cost_micro_usd,
                    SUM(src.output_cost_micro_usd)::bigint AS output_cost_micro_usd,
                    SUM(src.cache_read_cost_micro_usd)::bigint AS cache_read_cost_micro_usd,
                    SUM(src.cache_creation_cost_micro_usd)::bigint AS cache_creation_cost_micro_usd,
                    SUM(src.reasoning_cost_micro_usd)::bigint AS reasoning_cost_micro_usd,
                    SUM(src.audio_cost_micro_usd)::bigint AS audio_cost_micro_usd,
                    SUM(src.tts_cost_micro_usd)::bigint AS tts_cost_micro_usd,
                    SUM(src.total_cost_micro_usd)::bigint AS total_cost_micro_usd
                FROM usage_ctx_patch AS patch
                JOIN llm_usage_daily AS src ON src.id = patch.src_id
                GROUP BY
                    src.organization_id,
                    COALESCE(src.workspace_id, '{_ZERO_UUID}'::uuid),
                    src.product_section,
                    src.model,
                    src.usage_date,
                    COALESCE(src.usage_kind, 'llm'),
                    patch.new_context
                HAVING COUNT(*) > 1
            ),
            updated_self_keepers AS (
                UPDATE llm_usage_daily AS keeper
                SET prompt_tokens = g.prompt_tokens,
                    completion_tokens = g.completion_tokens,
                    cache_read_tokens = g.cache_read_tokens,
                    cache_creation_tokens = g.cache_creation_tokens,
                    reasoning_tokens = g.reasoning_tokens,
                    audio_seconds = g.audio_seconds,
                    tts_characters = g.tts_characters,
                    call_count = g.call_count,
                    input_cost_micro_usd = g.input_cost_micro_usd,
                    output_cost_micro_usd = g.output_cost_micro_usd,
                    cache_read_cost_micro_usd = g.cache_read_cost_micro_usd,
                    cache_creation_cost_micro_usd = g.cache_creation_cost_micro_usd,
                    reasoning_cost_micro_usd = g.reasoning_cost_micro_usd,
                    audio_cost_micro_usd = g.audio_cost_micro_usd,
                    tts_cost_micro_usd = g.tts_cost_micro_usd,
                    total_cost_micro_usd = g.total_cost_micro_usd,
                    updated_at = now()
                FROM patch_groups AS g
                WHERE keeper.id = g.keep_id
                RETURNING keeper.id
            ),
            dropped_peers AS (
                DELETE FROM llm_usage_daily AS src
                USING usage_ctx_patch AS src_patch,
                      patch_groups AS g,
                      llm_usage_daily AS peer,
                      usage_ctx_patch AS peer_patch
                WHERE src.id = src_patch.src_id
                  AND peer.id = g.keep_id
                  AND peer_patch.src_id = peer.id
                  AND src.id <> peer.id
                  AND src.organization_id = peer.organization_id
                  AND src.product_section = peer.product_section
                  AND src.model = peer.model
                  AND src.usage_date = peer.usage_date
                  AND COALESCE(src.usage_kind, 'llm') = COALESCE(peer.usage_kind, 'llm')
                  AND src.workspace_id IS NOT DISTINCT FROM peer.workspace_id
                  AND src_patch.new_context = peer_patch.new_context
                RETURNING src.id
            )
            DELETE FROM usage_ctx_patch AS patch
            USING dropped_peers AS d
            WHERE patch.src_id = d.id
            """
        )
    )

    # Step 3: Every remaining staged row now has a guaranteed-unique target key.
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
    if _table_exists(db, "call_import_evaluations"):
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
    if _table_exists(db, "call_import_rows") and _table_exists(db, "call_imports"):
        stage_context_select(
            db,
            """
            SELECT u.id,
                   u.context || jsonb_build_object(
                       'call_import_id', ci.id::text
                   )
            FROM llm_usage_daily AS u
            JOIN call_import_rows AS cir
              ON cir.id = (u.context->>'call_import_row_id')::uuid
            JOIN call_imports AS ci
              ON ci.id = cir.call_import_id
             AND ci.organization_id = u.organization_id
            WHERE NOT (u.context ? 'call_import_id')
              AND u.context ? 'call_import_row_id'
              AND u.context->>'call_import_row_id' ~ :uuid_re
            """,
            {"uuid_re": _UUID_RE},
        )
    if _table_exists(db, "call_import_evaluation_rows") and _table_exists(
        db, "call_import_evaluations"
    ):
        stage_context_select(
            db,
            """
            SELECT u.id,
                   u.context
                       || jsonb_build_object('evaluation_id', e.id::text)
                       || jsonb_build_object('call_import_id', e.call_import_id::text)
            FROM llm_usage_daily AS u
            JOIN call_import_evaluation_rows AS er
              ON er.id = (u.context->>'evaluation_row_id')::uuid
            JOIN call_import_evaluations AS e
              ON e.id = er.evaluation_id
             AND e.organization_id = u.organization_id
            WHERE u.context ? 'evaluation_row_id'
              AND u.context->>'evaluation_row_id' ~ :uuid_re
              AND (
                NOT (u.context ? 'evaluation_id')
                OR NOT (u.context ? 'call_import_id')
              )
            """,
            {"uuid_re": _UUID_RE},
        )


def _chunks(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


_IMPORT_ORPHAN_SQL = """
SELECT DISTINCT context->>'call_import_row_id'
FROM llm_usage_daily
WHERE context ? 'call_import_row_id'
  AND NOT (context ? 'call_import_id')
  AND context->>'call_import_row_id' ~ :uuid_re
  AND context->>'call_import_row_id' > :cursor
ORDER BY 1
LIMIT :limit
"""

_EVAL_ORPHAN_SQL = """
SELECT DISTINCT context->>'evaluation_row_id'
FROM llm_usage_daily
WHERE context ? 'evaluation_row_id'
  AND (
    NOT (context ? 'evaluation_id')
    OR NOT (context ? 'call_import_id')
  )
  AND context->>'evaluation_row_id' ~ :uuid_re
  AND context->>'evaluation_row_id' > :cursor
ORDER BY 1
LIMIT :limit
"""


def _orphan_page(db: Session, sql: str, cursor: str) -> list[str]:
    rows = db.execute(
        text(sql),
        {"uuid_re": _UUID_RE, "limit": _ORPHAN_BATCH_LIMIT, "cursor": cursor},
    ).all()
    return [str(row[0]) for row in rows if row[0]]


def repair_orphaned_row_context(db: Session) -> None:
    """Resolve row ids that live on shards into catalog context keys.

    Ids are walked in order. A page of deleted ids only moves the cursor
    forward, so later live ids are still repaired.
    """
    from app.db_sharding.pool_manager import db_pool_manager

    if not (db_pool_manager.sharding_enabled and db_pool_manager.router):
        return

    import_cursor = ""
    eval_cursor = ""
    import_done = False
    eval_done = False
    while not (import_done and eval_done):
        import_row_ids: list[str] = []
        eval_row_ids: list[str] = []
        if not import_done:
            import_row_ids = _orphan_page(db, _IMPORT_ORPHAN_SQL, import_cursor)
            if not import_row_ids or import_row_ids[-1] <= import_cursor:
                import_done = True
                import_row_ids = []
            else:
                import_cursor = import_row_ids[-1]
        if not eval_done:
            eval_row_ids = _orphan_page(db, _EVAL_ORPHAN_SQL, eval_cursor)
            if not eval_row_ids or eval_row_ids[-1] <= eval_cursor:
                eval_done = True
                eval_row_ids = []
            else:
                eval_cursor = eval_row_ids[-1]
        if not import_row_ids and not eval_row_ids:
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
                            WHERE id = ANY(CAST(:ids AS uuid[]))
                            """
                        ),
                        {"ids": list(batch)},
                    ).all()
                    import_by_row.update(
                        {row[0]: row[1] for row in found if row[0] and row[1]}
                    )
                for batch in _chunks(eval_row_ids, _BATCH):
                    found = session.execute(
                        text(
                            """
                            SELECT id::text, evaluation_id::text
                            FROM call_import_evaluation_rows
                            WHERE id = ANY(CAST(:ids AS uuid[]))
                            """
                        ),
                        {"ids": list(batch)},
                    ).all()
                    eval_by_row.update(
                        {row[0]: row[1] for row in found if row[0] and row[1]}
                    )
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
                    WHERE id = ANY(CAST(:ids AS uuid[]))
                    """
                ),
                {"ids": list(batch)},
            ).all()
            eval_to_import.update(
                {row[0]: row[1] for row in found if row[0] and row[1]}
            )

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
            if pairs:
                stage_context_pairs(db, pairs)

        if eval_by_row:
            rows = db.execute(
                text(
                    """
                    SELECT id::text, context
                    FROM llm_usage_daily
                    WHERE context ? 'evaluation_row_id'
                      AND (
                        NOT (context ? 'evaluation_id')
                        OR NOT (context ? 'call_import_id')
                      )
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
                before = dict(ctx)
                ctx.setdefault("evaluation_id", eval_id)
                import_id = eval_to_import.get(eval_id)
                if import_id:
                    ctx.setdefault("call_import_id", import_id)
                if ctx != before:
                    pairs.append((str(src_id), ctx))
            if pairs:
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
