"""
Migration: Extend the ``callimportstatus`` Postgres enum with the new
staged-flow values.

Migration 035 added the ``source_*`` / ``available_sheets`` /
``skipped_columns`` columns and relaxed ``provider`` to nullable, but
relied on the application-side ``CallImportStatus`` Python enum being
the sole source of truth for valid values. That assumption was wrong:
the ``status`` column on ``call_imports`` is backed by a native
Postgres ``ENUM`` (the SQLAlchemy ``Enum(CallImportStatus, ...)``
column type creates one when the table is first materialised), so the
DB will reject any value the enum type doesn't know about — even if
the Python enum accepts it.

This migration adds ``'uploaded'`` and ``'mapped'`` to the existing
``callimportstatus`` Postgres enum. Both values are added with
``IF NOT EXISTS`` so the migration is safe to re-run.

Why a separate migration:
  * 035 may already be marked as applied in ``schema_migrations`` on
    environments that picked up the column changes before this fix
    landed. Stuffing the enum changes back into 035 wouldn't re-run.
  * Postgres 15 (what we run in docker-compose) supports
    ``ALTER TYPE ... ADD VALUE IF NOT EXISTS`` inside a transaction
    block, so this is a single-statement, single-commit migration.

Side note: not every environment will have the Postgres enum in
place. Some test / fresh-install environments use a plain VARCHAR
column (depends on whether ``Base.metadata.create_all()`` ran before
the original ``call_imports`` migration). The upgrade is wrapped in a
``DO`` block so we no-op cleanly when the enum type is missing.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add 'uploaded' and 'mapped' to the callimportstatus Postgres enum "
    "so the staged call-import flow can persist its new statuses."
)


def _enum_type_exists(db: Session) -> bool:
    """True if the ``callimportstatus`` Postgres enum type is defined."""
    row = db.execute(
        text(
            """
            SELECT 1
            FROM pg_type
            WHERE typname = 'callimportstatus'
            """
        )
    ).first()
    return row is not None


def _enum_has_value(db: Session, value: str) -> bool:
    """True if ``value`` is already part of the ``callimportstatus`` enum."""
    row = db.execute(
        text(
            """
            SELECT 1
            FROM pg_enum e
            JOIN pg_type t ON t.oid = e.enumtypid
            WHERE t.typname = 'callimportstatus'
              AND e.enumlabel = :value
            """
        ),
        {"value": value},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _enum_type_exists(db):
        # Plain VARCHAR column on this environment — nothing to do.
        # Application code already validates against ``CallImportStatus``.
        print(
            "callimportstatus enum type does not exist; column is likely "
            "VARCHAR-backed, nothing to migrate."
        )
        return

    for value in ("uploaded", "mapped"):
        if _enum_has_value(db, value):
            print(
                f"callimportstatus already has value '{value}', skipping..."
            )
            continue
        db.execute(
            text(
                f"ALTER TYPE callimportstatus ADD VALUE IF NOT EXISTS '{value}'"
            )
        )
        # Commit immediately so the new value is visible to subsequent
        # statements. Postgres 12+ no longer rejects ALTER TYPE inside a
        # transaction, but the new value is only usable in *subsequent*
        # transactions, so we explicitly commit each one to keep the
        # idempotency check above accurate on retry.
        db.commit()
        print(f"Added '{value}' to callimportstatus enum")


def downgrade(db: Session):
    # Postgres doesn't support dropping individual enum values. The
    # closest workaround would be:
    #   1. CREATE TYPE callimportstatus_new AS ENUM (<old values only>);
    #   2. ALTER TABLE call_imports ALTER COLUMN status TYPE
    #      callimportstatus_new USING status::text::callimportstatus_new;
    #   3. DROP TYPE callimportstatus; RENAME callimportstatus_new ->
    #      callimportstatus.
    # That's a destructive rewrite that we don't want to ship as the
    # default downgrade path (any row already at 'uploaded'/'mapped'
    # would fail the cast). Leaving downgrade as a no-op: re-applying
    # the enum values is harmless, and a real rollback would need to
    # be authored by hand.
    print(
        "Downgrade for enum additions is a no-op; Postgres does not "
        "support removing individual enum values safely."
    )
