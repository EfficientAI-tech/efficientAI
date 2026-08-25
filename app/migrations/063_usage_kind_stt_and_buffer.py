"""Migration: STT usage_kind/audio_seconds + Redis-fallback pending buffer."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add usage_kind/audio_seconds to llm_usage_daily and usage_pending_buffer "
    "for durable STT + LLM usage when Redis is unavailable"
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


def _dedupe_llm_usage_daily(db: Session) -> int:
    """Merge duplicate bucket rows so the unique index can be created.

    Keeps the oldest row (MIN id), sums metrics into it, deletes extras.
    """
    db.execute(
        text(
            f"""
            WITH dupes AS (
                SELECT
                    organization_id,
                    COALESCE(
                        workspace_id,
                        '{_ZERO_UUID}'::uuid
                    ) AS ws_key,
                    product_section,
                    model,
                    COALESCE(
                        resource_id,
                        '{_ZERO_UUID}'::uuid
                    ) AS rid_key,
                    usage_date,
                    COALESCE(usage_kind, 'llm') AS kind_key,
                    MIN(id::text)::uuid AS keep_id,
                    SUM(prompt_tokens)::bigint AS prompt_tokens,
                    SUM(completion_tokens)::bigint AS completion_tokens,
                    SUM(cache_read_tokens)::bigint AS cache_read_tokens,
                    SUM(cache_creation_tokens)::bigint AS cache_creation_tokens,
                    SUM(reasoning_tokens)::bigint AS reasoning_tokens,
                    SUM(COALESCE(audio_seconds, 0))::bigint AS audio_seconds,
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
                    COALESCE(resource_id, '{_ZERO_UUID}'::uuid),
                    usage_date,
                    COALESCE(usage_kind, 'llm')
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
              AND u.resource_id IS NOT DISTINCT FROM peer.resource_id
            """
        )
    )
    return int(result.rowcount or 0)


def _ensure_unique_bucket_index(db: Session) -> None:
    """Drop legacy/broken unique index and recreate with usage_kind."""
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
                COALESCE(resource_id, '{_ZERO_UUID}'::uuid),
                usage_date,
                usage_kind
            )
            """
        )
    )


def _ensure_llm_usage_daily_base_columns(db: Session) -> None:
    """Align pre-062 tables with the 062 schema before dedupe/index steps."""
    if not _column_exists(db, "llm_usage_daily", "resource_id"):
        db.execute(text("ALTER TABLE llm_usage_daily ADD COLUMN resource_id UUID"))
    if not _column_exists(db, "llm_usage_daily", "resource_type"):
        db.execute(
            text("ALTER TABLE llm_usage_daily ADD COLUMN resource_type VARCHAR(64)")
        )
    if not _column_exists(db, "llm_usage_daily", "updated_at"):
        db.execute(
            text(
                """
                ALTER TABLE llm_usage_daily
                ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                """
            )
        )


def upgrade(db: Session):
    if not _table_exists(db, "llm_usage_daily"):
        print("llm_usage_daily missing; run 062 first — skipping 063")
        db.commit()
        return

    _ensure_llm_usage_daily_base_columns(db)

    if not _column_exists(db, "llm_usage_daily", "usage_kind"):
        db.execute(
            text(
                """
                ALTER TABLE llm_usage_daily
                ADD COLUMN usage_kind VARCHAR(16) NOT NULL DEFAULT 'llm'
                """
            )
        )

    if not _column_exists(db, "llm_usage_daily", "audio_seconds"):
        db.execute(
            text(
                """
                ALTER TABLE llm_usage_daily
                ADD COLUMN audio_seconds BIGINT NOT NULL DEFAULT 0
                """
            )
        )

    removed = _dedupe_llm_usage_daily(db)
    if removed:
        print(f"Merged/removed {removed} duplicate llm_usage_daily row(s)")

    _ensure_unique_bucket_index(db)

    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_llm_usage_daily_org_kind_date
            ON llm_usage_daily (organization_id, usage_kind, usage_date)
            """
        )
    )
    print("Ensured usage_kind + audio_seconds + unique bucket index")

    if not _table_exists(db, "usage_pending_buffer"):
        db.execute(
            text(
                """
                CREATE TABLE usage_pending_buffer (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL,
                    workspace_id UUID,
                    product_section VARCHAR(64) NOT NULL,
                    model VARCHAR(255) NOT NULL,
                    context JSONB NOT NULL DEFAULT '{}'::jsonb,
                    usage_date DATE NOT NULL,
                    usage_kind VARCHAR(16) NOT NULL DEFAULT 'llm',
                    prompt_tokens BIGINT NOT NULL DEFAULT 0,
                    completion_tokens BIGINT NOT NULL DEFAULT 0,
                    cache_read_tokens BIGINT NOT NULL DEFAULT 0,
                    cache_creation_tokens BIGINT NOT NULL DEFAULT 0,
                    reasoning_tokens BIGINT NOT NULL DEFAULT 0,
                    audio_seconds BIGINT NOT NULL DEFAULT 0,
                    call_count BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_usage_pending_buffer_org_created
                ON usage_pending_buffer (organization_id, created_at)
                """
            )
        )
        print("Created usage_pending_buffer")

    if not _table_exists(db, "usage_committed_claims"):
        db.execute(
            text(
                """
                CREATE TABLE usage_committed_claims (
                    claim_key TEXT PRIMARY KEY,
                    organization_id UUID NOT NULL,
                    committed_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_usage_committed_claims_committed_at
                ON usage_committed_claims (committed_at)
                """
            )
        )
        print("Created usage_committed_claims")

    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS usage_committed_claims"))
    db.execute(text("DROP TABLE IF EXISTS usage_pending_buffer"))
    db.execute(text("DROP INDEX IF EXISTS ix_llm_usage_daily_org_kind_date"))
    # Keep usage_kind/audio_seconds columns on downgrade to avoid data loss.
    db.commit()
