"""
Migration: In-org Workspaces (project-style isolation for call imports + metrics).

Adds:
  * ``workspaces`` table - one row per (organization, named workspace).
  * ``workspace_id`` FK column on ``call_imports``, ``metrics``, and
    ``call_import_evaluations`` (nullable in step 1, NOT NULL after backfill).
  * Per-org "Default" workspace seeded for every existing organization.
  * Backfills ``workspace_id`` on every existing row to that org's Default
    workspace, so the v1 rollout doesn't strand any data.

Idempotent: every step checks for prior state before applying.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add workspaces table and workspace_id scoping on call_imports, "
    "metrics, and call_import_evaluations; backfill a Default workspace "
    "per organization."
)


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
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


def upgrade(db: Session):
    # 1. workspaces table.
    if not _table_exists(db, "workspaces"):
        db.execute(
            text(
                """
                CREATE TABLE workspaces (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    slug VARCHAR(255) NOT NULL,
                    is_default BOOLEAN NOT NULL DEFAULT FALSE,
                    created_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    CONSTRAINT uq_workspaces_org_slug UNIQUE (organization_id, slug)
                )
                """
            )
        )
        print("Created workspaces table")
    else:
        print("workspaces table already exists, skipping CREATE...")

    # Belt-and-braces: ensure `id` has the DB-side DEFAULT even when the
    # table was created by `Base.metadata.create_all` (init_db runs
    # before migrations). create_all does not emit DEFAULT clauses for
    # Python-side `default=uuid.uuid4`, which leaves the column NOT NULL
    # but with no default, breaking the raw-SQL seed below.
    db.execute(
        text(
            "ALTER TABLE workspaces ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        )
    )

    # Indexes always created with IF NOT EXISTS so they're laid down
    # regardless of whether this migration or create_all made the table.
    # The partial unique index encodes "at most one default workspace
    # per org" - critical for the seed below being idempotent.
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_org_default
            ON workspaces(organization_id)
            WHERE is_default
            """
        )
    )
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_workspaces_organization_id "
            "ON workspaces(organization_id)"
        )
    )

    # 2. Seed one Default workspace per organization (idempotent on the
    # partial unique index above). `id` is supplied explicitly so this
    # works even if the column happens to have no DEFAULT yet (e.g. an
    # earlier deploy that ran the migration before this fix landed).
    db.execute(
        text(
            """
            INSERT INTO workspaces (id, organization_id, name, slug, is_default)
            SELECT gen_random_uuid(), o.id, 'Default', 'default', TRUE
            FROM organizations o
            WHERE NOT EXISTS (
                SELECT 1 FROM workspaces w
                WHERE w.organization_id = o.id AND w.is_default IS TRUE
            )
            """
        )
    )
    print("Seeded Default workspace for organizations missing one")

    # 3. Add workspace_id column on each scoped table (nullable for now
    # so the backfill below can run without violating constraints).
    for table_name in ("call_imports", "metrics", "call_import_evaluations"):
        if not _column_exists(db, table_name, "workspace_id"):
            db.execute(
                text(
                    f"""
                    ALTER TABLE {table_name}
                    ADD COLUMN workspace_id UUID NULL
                        REFERENCES workspaces(id) ON DELETE RESTRICT
                    """
                )
            )
            print(f"Added {table_name}.workspace_id (nullable)")
        else:
            print(f"{table_name}.workspace_id already exists, skipping...")

    # 4. Backfill workspace_id = org's Default workspace for any rows
    # that don't have one yet. Done with set-based UPDATE so it's cheap
    # even for orgs with millions of imports.
    for table_name in ("call_imports", "metrics", "call_import_evaluations"):
        db.execute(
            text(
                f"""
                UPDATE {table_name} t
                SET workspace_id = w.id
                FROM workspaces w
                WHERE w.organization_id = t.organization_id
                  AND w.is_default IS TRUE
                  AND t.workspace_id IS NULL
                """
            )
        )
        print(f"Backfilled workspace_id on {table_name}")

    # 5. Once every row has a workspace, lock the column NOT NULL and
    # add a covering index for the (org, workspace) listing pattern.
    for table_name, index_name in (
        ("call_imports", "ix_call_imports_org_workspace"),
        ("metrics", "ix_metrics_org_workspace"),
        ("call_import_evaluations", "ix_call_import_evaluations_org_workspace"),
    ):
        # Defensive: if the table somehow has NULLs left (e.g. a row
        # was inserted between the backfill and this step in a long
        # migration), surface a clear error rather than silently
        # failing the constraint with a noisy stack trace.
        leftover = db.execute(
            text(f"SELECT COUNT(*) FROM {table_name} WHERE workspace_id IS NULL")
        ).scalar()
        if leftover and leftover > 0:
            raise RuntimeError(
                f"Cannot mark {table_name}.workspace_id NOT NULL: "
                f"{leftover} row(s) still NULL after backfill."
            )

        db.execute(
            text(f"ALTER TABLE {table_name} ALTER COLUMN workspace_id SET NOT NULL")
        )
        print(f"Set {table_name}.workspace_id NOT NULL")

        if not _index_exists(db, index_name):
            db.execute(
                text(
                    f"CREATE INDEX {index_name} "
                    f"ON {table_name}(organization_id, workspace_id)"
                )
            )
            print(f"Created index {index_name}")

    db.commit()
    print("Workspaces schema is in place")


def downgrade(db: Session):
    for table_name, index_name in (
        ("call_imports", "ix_call_imports_org_workspace"),
        ("metrics", "ix_metrics_org_workspace"),
        ("call_import_evaluations", "ix_call_import_evaluations_org_workspace"),
    ):
        db.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        if _column_exists(db, table_name, "workspace_id"):
            db.execute(
                text(f"ALTER TABLE {table_name} DROP COLUMN workspace_id")
            )

    db.execute(text("DROP INDEX IF EXISTS uq_workspaces_org_default"))
    db.execute(text("DROP INDEX IF EXISTS ix_workspaces_organization_id"))
    db.execute(text("DROP TABLE IF EXISTS workspaces"))
    db.commit()
