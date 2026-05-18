"""
Migration: Backfill multi-credential columns for integrations / aiproviders / telephony_integrations.

The ORM models already declare ``is_default`` (and ``last_tested_at`` /
``name``) for these tables, but historical databases were created before
those columns existed. This migration is idempotent and only adds what is
missing, plus the partial unique index that pins at most one
``is_default = TRUE`` row per ``(org, provider/platform)``.

Adding these columns here unblocks the configurable Call Imports flow,
which needs to pin a specific telephony credential row per upload (so the
worker can fetch recordings using *that* credential rather than the org's
default).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add multi-credential columns and partial unique defaults to "
    "integrations / aiproviders / telephony_integrations"
)


def _column_exists(db: Session, table: str, column: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table, "column_name": column},
    ).first()
    return row is not None


def _table_exists(db: Session, table: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table},
    ).first()
    return row is not None


def _index_exists(db: Session, index_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM pg_indexes WHERE indexname = :index_name
            """
        ),
        {"index_name": index_name},
    ).first()
    return row is not None


def _add_is_default(db: Session, table: str) -> None:
    if _column_exists(db, table, "is_default"):
        return
    db.execute(
        text(
            f"ALTER TABLE {table} ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )
    print(f"Added {table}.is_default")


def _add_last_tested_at(db: Session, table: str) -> None:
    if _column_exists(db, table, "last_tested_at"):
        return
    db.execute(
        text(
            f"ALTER TABLE {table} ADD COLUMN last_tested_at TIMESTAMP WITH TIME ZONE NULL"
        )
    )
    print(f"Added {table}.last_tested_at")


def _add_name(db: Session, table: str) -> None:
    if _column_exists(db, table, "name"):
        return
    db.execute(text(f"ALTER TABLE {table} ADD COLUMN name VARCHAR(255) NULL"))
    print(f"Added {table}.name")


def _create_partial_default_index(
    db: Session, *, table: str, provider_column: str, index_name: str
) -> None:
    if _index_exists(db, index_name):
        return
    db.execute(
        text(
            f"""
            CREATE UNIQUE INDEX {index_name}
            ON {table} (organization_id, {provider_column})
            WHERE is_default = TRUE
            """
        )
    )
    print(f"Created partial unique index {index_name}")


def _backfill_default(
    db: Session, *, table: str, provider_column: str
) -> None:
    """Promote one row per ``(org, provider)`` to ``is_default = TRUE``.

    Picks the most recently updated active row, mirroring the resolver
    fallback so behavior pre/post migration matches.
    """
    db.execute(
        text(
            f"""
            UPDATE {table} t
            SET is_default = TRUE
            FROM (
                SELECT DISTINCT ON (organization_id, {provider_column}) id
                FROM {table}
                WHERE is_active = TRUE
                ORDER BY organization_id, {provider_column},
                         updated_at DESC NULLS LAST,
                         created_at DESC NULLS LAST
            ) chosen
            WHERE t.id = chosen.id
              AND NOT EXISTS (
                  SELECT 1 FROM {table} other
                  WHERE other.organization_id = t.organization_id
                    AND lower(other.{provider_column}) = lower(t.{provider_column})
                    AND other.is_default = TRUE
              )
            """
        )
    )


def upgrade(db: Session):
    # integrations table (voice platforms: retell, vapi, ...)
    if _table_exists(db, "integrations"):
        _add_is_default(db, "integrations")
        if not _column_exists(db, "integrations", "name"):
            _add_name(db, "integrations")
        _backfill_default(db, table="integrations", provider_column="platform")
        _create_partial_default_index(
            db,
            table="integrations",
            provider_column="platform",
            index_name="uq_integrations_default_per_org_platform",
        )

    # aiproviders table (openai, anthropic, ...)
    if _table_exists(db, "aiproviders"):
        _add_is_default(db, "aiproviders")
        _add_last_tested_at(db, "aiproviders")
        _backfill_default(db, table="aiproviders", provider_column="provider")
        _create_partial_default_index(
            db,
            table="aiproviders",
            provider_column="provider",
            index_name="uq_aiproviders_default_per_org_provider",
        )

    # telephony_integrations table (plivo, exotel, ...)
    if _table_exists(db, "telephony_integrations"):
        _add_is_default(db, "telephony_integrations")
        _add_last_tested_at(db, "telephony_integrations")
        _add_name(db, "telephony_integrations")
        _backfill_default(
            db, table="telephony_integrations", provider_column="provider"
        )
        _create_partial_default_index(
            db,
            table="telephony_integrations",
            provider_column="provider",
            index_name="uq_telephony_default_per_org_provider",
        )

    db.commit()
    print("Multi-credential columns and indexes are in place")


def downgrade(db: Session):
    for index_name in (
        "uq_integrations_default_per_org_platform",
        "uq_aiproviders_default_per_org_provider",
        "uq_telephony_default_per_org_provider",
    ):
        db.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
    # We intentionally do NOT drop columns to avoid data loss; downgrade is
    # only meant to remove the partial indexes if they cause issues.
    db.commit()
