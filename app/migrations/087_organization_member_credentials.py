"""Add per-organization member credentials (password + session_epoch).

Production-safe / idempotent:
  - CREATE TABLE only when missing; indexes/constraints use IF NOT EXISTS.
  - Backfill INSERTs missing rows only — never updates existing credentials.
  - Explicit gen_random_uuid() in SELECT (works even if id has no DB default).
  - Safe to re-run after a partial failure (empty table, failed insert, etc.).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add organization_member_credentials for org-scoped passwords and sessions"

MIGRATION_SCOPE = "catalog"


def _table_exists(db: Session, table_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    )
    return bool(result.scalar())


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table_name
                  AND column_name = :column_name
            )
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


def upgrade(db: Session) -> None:
    if not _table_exists(db, "organization_member_credentials"):
        db.execute(
            text(
                """
                CREATE TABLE organization_member_credentials (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    password_hash VARCHAR(255),
                    auth_provider VARCHAR(50),
                    session_epoch INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_org_member_credentials_org_user
                        UNIQUE (organization_id, user_id)
                )
                """
            )
        )

    # Belt-and-braces: create_all() may have created the table without a DB
    # default on id; the backfill always supplies id explicitly, but set the
    # default anyway for future app inserts.
    db.execute(
        text(
            "ALTER TABLE organization_member_credentials "
            "ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        )
    )

    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_org_member_credentials_org_user
                ON organization_member_credentials (organization_id, user_id)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_org_member_credentials_user_id
                ON organization_member_credentials (user_id)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_org_member_credentials_org_id
                ON organization_member_credentials (organization_id)
            """
        )
    )

    # Backfill one credential row per membership from the legacy global user
    # password/session. INSERT-only: existing rows (e.g. from a prior partial
    # run or app writes) are left untouched.
    session_epoch_expr = (
        "COALESCE(u.session_epoch, 0)"
        if _column_exists(db, "users", "session_epoch")
        else "0"
    )
    db.execute(
        text(
            f"""
            INSERT INTO organization_member_credentials (
                id,
                organization_id,
                user_id,
                password_hash,
                auth_provider,
                session_epoch,
                created_at,
                updated_at
            )
            SELECT
                gen_random_uuid(),
                om.organization_id,
                om.user_id,
                u.password_hash,
                u.auth_provider,
                {session_epoch_expr},
                NOW(),
                NOW()
            FROM organization_members om
            INNER JOIN users u ON u.id = om.user_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM organization_member_credentials c
                WHERE c.organization_id = om.organization_id
                  AND c.user_id = om.user_id
            )
            """
        )
    )


def downgrade(db: Session) -> None:
    if _table_exists(db, "organization_member_credentials"):
        db.execute(text("DROP TABLE organization_member_credentials"))
