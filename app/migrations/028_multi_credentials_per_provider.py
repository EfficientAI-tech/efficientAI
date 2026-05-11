"""
Migration: Allow multiple API keys per provider.

Removes the (organization_id, provider) UNIQUE constraints on aiproviders
and telephony_integrations and adds an `is_default` boolean column on
integrations, aiproviders, and telephony_integrations so that the system
can resolve a single default credential per (org, provider) when no
explicit credential is selected.

Backfills `is_default = TRUE` on the single existing row per (org,
provider) so all existing call sites resolving by provider name keep
working untouched.

Adds partial UNIQUE indexes that enforce at most one default credential
per (org, provider) at the DB level.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Allow multiple credentials per provider; add is_default + partial unique indexes"
)


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return result.first() is not None


def _constraint_exists(db: Session, constraint_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.table_constraints
            WHERE constraint_name = :constraint_name
            """
        ),
        {"constraint_name": constraint_name},
    )
    return result.first() is not None


def _index_exists(db: Session, index_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT 1
            FROM pg_indexes
            WHERE indexname = :index_name
            """
        ),
        {"index_name": index_name},
    )
    return result.first() is not None


def _add_is_default_column(db: Session, table_name: str) -> None:
    if _column_exists(db, table_name, "is_default"):
        print(f"{table_name}.is_default already exists, skipping...")
        return
    db.execute(
        text(
            f"ALTER TABLE {table_name} "
            "ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )
    print(f"Added {table_name}.is_default")


def _drop_constraint_if_exists(
    db: Session, table_name: str, constraint_name: str
) -> None:
    if not _constraint_exists(db, constraint_name):
        print(f"Constraint {constraint_name} not found, skipping drop...")
        return
    db.execute(
        text(f"ALTER TABLE {table_name} DROP CONSTRAINT {constraint_name}")
    )
    print(f"Dropped constraint {constraint_name} on {table_name}")


def upgrade(db: Session):
    _add_is_default_column(db, "integrations")
    _add_is_default_column(db, "aiproviders")
    _add_is_default_column(db, "telephony_integrations")

    # Telephony integrations historically had no friendly name. Add one so
    # users can distinguish multiple credentials for the same provider in
    # the UI.
    if not _column_exists(db, "telephony_integrations", "name"):
        db.execute(
            text("ALTER TABLE telephony_integrations ADD COLUMN name VARCHAR(255)")
        )
        print("Added telephony_integrations.name column")

    _drop_constraint_if_exists(db, "aiproviders", "unique_org_provider")
    _drop_constraint_if_exists(
        db, "telephony_integrations", "uq_telephony_integration_org_provider"
    )

    # Backfill: mark exactly one row per (org, provider/platform) as default,
    # preferring active rows. We use DISTINCT ON to deterministically pick
    # the most recently updated active row when duplicates already exist.
    db.execute(
        text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY organization_id, LOWER(platform)
                           ORDER BY is_active DESC, updated_at DESC, created_at DESC
                       ) AS rn
                FROM integrations
            )
            UPDATE integrations
            SET is_default = TRUE
            FROM ranked
            WHERE integrations.id = ranked.id AND ranked.rn = 1
            """
        )
    )
    db.execute(
        text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY organization_id, LOWER(provider)
                           ORDER BY is_active DESC, updated_at DESC, created_at DESC
                       ) AS rn
                FROM aiproviders
            )
            UPDATE aiproviders
            SET is_default = TRUE
            FROM ranked
            WHERE aiproviders.id = ranked.id AND ranked.rn = 1
            """
        )
    )
    db.execute(
        text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY organization_id, LOWER(provider)
                           ORDER BY is_active DESC, updated_at DESC, created_at DESC
                       ) AS rn
                FROM telephony_integrations
            )
            UPDATE telephony_integrations
            SET is_default = TRUE
            FROM ranked
            WHERE telephony_integrations.id = ranked.id AND ranked.rn = 1
            """
        )
    )

    if not _index_exists(db, "uq_default_aiprovider"):
        db.execute(
            text(
                "CREATE UNIQUE INDEX uq_default_aiprovider "
                "ON aiproviders(organization_id, LOWER(provider)) "
                "WHERE is_default"
            )
        )
        print("Created partial unique index uq_default_aiprovider")
    if not _index_exists(db, "uq_default_telephony"):
        db.execute(
            text(
                "CREATE UNIQUE INDEX uq_default_telephony "
                "ON telephony_integrations(organization_id, LOWER(provider)) "
                "WHERE is_default"
            )
        )
        print("Created partial unique index uq_default_telephony")
    if not _index_exists(db, "uq_default_voice_integration"):
        db.execute(
            text(
                "CREATE UNIQUE INDEX uq_default_voice_integration "
                "ON integrations(organization_id, LOWER(platform)) "
                "WHERE is_default AND is_active"
            )
        )
        print("Created partial unique index uq_default_voice_integration")

    db.commit()
    print("Successfully migrated to multi-credentials-per-provider schema")


def downgrade(db: Session):
    for index_name in (
        "uq_default_aiprovider",
        "uq_default_telephony",
        "uq_default_voice_integration",
    ):
        if _index_exists(db, index_name):
            db.execute(text(f"DROP INDEX IF EXISTS {index_name}"))

    for table_name in ("integrations", "aiproviders", "telephony_integrations"):
        if _column_exists(db, table_name, "is_default"):
            db.execute(text(f"ALTER TABLE {table_name} DROP COLUMN is_default"))

    db.commit()
