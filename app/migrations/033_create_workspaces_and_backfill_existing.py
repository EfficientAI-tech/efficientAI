"""
Migration: Create the ``workspaces`` table and seed the per-org Default.

Workspaces are the in-org isolation boundary for call imports, metrics,
and (in subsequent migrations) the rest of the resource model. Every
organization gets exactly one ``Default`` workspace which acts as the
safety net for legacy rows and for any request that arrives without an
``X-Workspace-Id`` header.

This migration:

1. Creates ``workspaces`` (with a partial unique index that enforces
   "at most one default per org").
2. Seeds one ``Default`` workspace per existing organization.
3. Adds ``workspace_id`` to ``metrics``, ``call_imports`` and
   ``call_import_evaluations`` (the three tables whose code already
   references the column) and backfills them to the org's default
   workspace, then promotes the column to NOT NULL with the proper FK.

Idempotent: every step checks for prior existence so reruns are safe.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Create workspaces table, seed per-org Default workspace, and backfill "
    "workspace_id on metrics / call_imports / call_import_evaluations"
)


def _table_exists(db: Session, table: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table},
    ).first()
    return row is not None


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


def _constraint_exists(db: Session, table: str, constraint: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.table_constraints
            WHERE table_name = :table_name AND constraint_name = :constraint_name
            """
        ),
        {"table_name": table, "constraint_name": constraint},
    ).first()
    return row is not None


def _create_workspaces_table(db: Session) -> None:
    if _table_exists(db, "workspaces"):
        print("workspaces table already exists, skipping CREATE")
        return

    db.execute(
        text(
            """
            CREATE TABLE workspaces (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id)
                    ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(255) NOT NULL,
                is_default BOOLEAN NOT NULL DEFAULT FALSE,
                created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_workspaces_org_slug UNIQUE (organization_id, slug)
            )
            """
        )
    )
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_workspaces_organization_id "
            "ON workspaces (organization_id)"
        )
    )
    # Enforce "at most one default workspace per org" with a partial
    # unique index. We can't express that purely in SQLAlchemy so it
    # lives here.
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_one_default_per_org
            ON workspaces (organization_id)
            WHERE is_default
            """
        )
    )
    print("Created workspaces table")


def _seed_default_workspaces(db: Session) -> None:
    """Ensure every existing org has exactly one Default workspace."""
    db.execute(
        text(
            """
            INSERT INTO workspaces (organization_id, name, slug, is_default)
            SELECT o.id, 'Default', 'default', TRUE
            FROM organizations o
            WHERE NOT EXISTS (
                SELECT 1 FROM workspaces w
                WHERE w.organization_id = o.id AND w.is_default = TRUE
            )
            """
        )
    )
    print("Seeded Default workspaces for any organization that lacked one")


def _add_workspace_id_from_org(db: Session, table: str) -> None:
    """Add ``workspace_id`` to ``table`` and backfill from org default.

    Pattern: nullable add → backfill → set NOT NULL → add FK + index.
    Splitting it like this keeps the column add cheap even on tables
    that already have lots of rows.
    """
    if _column_exists(db, table, "workspace_id"):
        # Column already present; just make sure backfill is complete
        # and the not-null + FK + index pieces are in place.
        print(f"{table}.workspace_id already exists, ensuring backfill is complete")
    else:
        db.execute(
            text(f"ALTER TABLE {table} ADD COLUMN workspace_id UUID NULL")
        )
        print(f"Added {table}.workspace_id (nullable)")

    # Backfill any row that's still missing a workspace_id by pointing
    # at the org's Default workspace. Safe to rerun.
    db.execute(
        text(
            f"""
            UPDATE {table} t
            SET workspace_id = w.id
            FROM workspaces w
            WHERE t.workspace_id IS NULL
              AND w.organization_id = t.organization_id
              AND w.is_default = TRUE
            """
        )
    )

    # Promote to NOT NULL once every row has a value.
    db.execute(
        text(f"ALTER TABLE {table} ALTER COLUMN workspace_id SET NOT NULL")
    )

    # FK to workspaces. ON DELETE RESTRICT so callers can't accidentally
    # delete a workspace that still has resources in it.
    fk_name = f"fk_{table}_workspace_id"
    if not _constraint_exists(db, table, fk_name):
        db.execute(
            text(
                f"""
                ALTER TABLE {table}
                ADD CONSTRAINT {fk_name}
                FOREIGN KEY (workspace_id)
                REFERENCES workspaces(id) ON DELETE RESTRICT
                """
            )
        )
        print(f"Added FK {fk_name}")

    index_name = f"ix_{table}_workspace_id"
    db.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {table} (workspace_id)"
        )
    )


def upgrade(db: Session):
    _create_workspaces_table(db)
    db.commit()

    _seed_default_workspaces(db)
    db.commit()

    for table in ("metrics", "call_imports", "call_import_evaluations"):
        if not _table_exists(db, table):
            print(f"Table {table} does not exist yet, skipping backfill")
            continue
        _add_workspace_id_from_org(db, table)
        db.commit()

    print("Workspaces table created and core tables backfilled")


def downgrade(db: Session):
    # Reverse order: drop the FK + columns, then drop the workspaces
    # table. Skipped silently for any object that's already gone so
    # downgrade is also idempotent.
    for table in ("call_import_evaluations", "call_imports", "metrics"):
        fk_name = f"fk_{table}_workspace_id"
        db.execute(
            text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {fk_name}")
        )
        db.execute(
            text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS workspace_id")
        )
    db.execute(text("DROP TABLE IF EXISTS workspaces CASCADE"))
    db.commit()
