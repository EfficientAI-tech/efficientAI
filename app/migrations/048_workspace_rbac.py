"""
Migration: Workspace RBAC (roles, memberships, backfill).

Adds:
  * ``workspace_roles`` table - org-scoped capability bundles (system + custom).
  * ``workspace_members`` table - user membership per workspace.
  * Seeds Viewer / Editor / Workspace Admin system roles per org.
  * Backfills every org member into every org workspace (preserves access on upgrade).

Idempotent: every step checks for prior state before applying.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add workspace_roles and workspace_members for capability-based workspace RBAC; "
    "seed system roles and backfill memberships."
)

SYSTEM_ROLES = (
    (
        "Viewer",
        "Read-only access to workspace resources.",
        sorted(
            {
                "calls.view",
                "metrics.view",
                "evals.view",
                "sim.view",
                "reports.view",
                "workspace.members.view",
            }
        ),
    ),
    (
        "Editor",
        "View and modify workspace resources without admin settings.",
        sorted(
            {
                "calls.view",
                "calls.import",
                "metrics.view",
                "metrics.manage",
                "evals.view",
                "evals.run",
                "sim.view",
                "sim.manage",
                "reports.view",
                "reports.generate",
                "workspace.members.view",
            }
        ),
    ),
    (
        "Workspace Admin",
        "Full access including workspace settings and member management.",
        sorted(
            {
                "calls.view",
                "calls.import",
                "calls.delete",
                "metrics.view",
                "metrics.manage",
                "evals.view",
                "evals.run",
                "sim.view",
                "sim.manage",
                "reports.view",
                "reports.generate",
                "workspace.settings",
                "workspace.members.view",
                "workspace.members.manage",
            }
        ),
    ),
)


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
        text("SELECT 1 FROM pg_indexes WHERE indexname = :index_name"),
        {"index_name": index_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _table_exists(db, "workspace_roles"):
        db.execute(
            text(
                """
                CREATE TABLE workspace_roles (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL
                        REFERENCES organizations(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    description TEXT NULL,
                    capabilities JSON NOT NULL DEFAULT '[]',
                    is_system BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    CONSTRAINT uq_workspace_roles_org_name
                        UNIQUE (organization_id, name)
                )
                """
            )
        )
        print("Created workspace_roles table")
    else:
        print("workspace_roles table already exists, skipping CREATE...")

    # Belt-and-braces: ensure ``id`` has the DB-side DEFAULT even when the
    # table was created by ``Base.metadata.create_all`` (init_db runs before
    # migrations). create_all does not emit DEFAULT clauses for Python-side
    # ``default=uuid.uuid4``, which leaves the column NOT NULL but with no
    # default, breaking the raw-SQL seed below.
    db.execute(
        text(
            "ALTER TABLE workspace_roles ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        )
    )

    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_workspace_roles_organization_id "
            "ON workspace_roles(organization_id)"
        )
    )

    if not _table_exists(db, "workspace_members"):
        db.execute(
            text(
                """
                CREATE TABLE workspace_members (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    workspace_id UUID NOT NULL
                        REFERENCES workspaces(id) ON DELETE CASCADE,
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role_id UUID NOT NULL
                        REFERENCES workspace_roles(id) ON DELETE RESTRICT,
                    added_by_user_id UUID NULL
                        REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    CONSTRAINT uq_workspace_members_ws_user
                        UNIQUE (workspace_id, user_id)
                )
                """
            )
        )
        print("Created workspace_members table")
    else:
        print("workspace_members table already exists, skipping CREATE...")

    db.execute(
        text(
            "ALTER TABLE workspace_members ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        )
    )

    for index_sql in (
        "CREATE INDEX IF NOT EXISTS ix_workspace_members_workspace_id "
        "ON workspace_members(workspace_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_members_user_id "
        "ON workspace_members(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_members_role_id "
        "ON workspace_members(role_id)",
    ):
        db.execute(text(index_sql))

    org_rows = db.execute(text("SELECT id FROM organizations")).fetchall()
    for (org_id,) in org_rows:
        role_ids: dict[str, str] = {}
        for name, desc, caps in SYSTEM_ROLES:
            existing = db.execute(
                text(
                    """
                    SELECT id FROM workspace_roles
                    WHERE organization_id = :org_id AND name = :name
                    """
                ),
                {"org_id": org_id, "name": name},
            ).first()
            if existing:
                role_ids[name] = str(existing[0])
                continue
            inserted = db.execute(
                text(
                    """
                    INSERT INTO workspace_roles
                        (id, organization_id, name, description, capabilities, is_system)
                    VALUES
                        (gen_random_uuid(), :org_id, :name, :description,
                         CAST(:capabilities AS JSON), TRUE)
                    RETURNING id
                    """
                ),
                {
                    "org_id": org_id,
                    "name": name,
                    "description": desc,
                    "capabilities": json.dumps(caps),
                },
            ).first()
            role_ids[name] = str(inserted[0])
        print(f"Seeded system workspace roles for org {org_id}")

        workspaces = db.execute(
            text("SELECT id FROM workspaces WHERE organization_id = :org_id"),
            {"org_id": org_id},
        ).fetchall()
        members = db.execute(
            text(
                """
                SELECT user_id, role FROM organization_members
                WHERE organization_id = :org_id
                """
            ),
            {"org_id": org_id},
        ).fetchall()

        for workspace_id, in workspaces:
            for user_id, org_role in members:
                role_name = "Workspace Admin"
                if org_role == "writer":
                    role_name = "Editor"
                elif org_role == "reader":
                    role_name = "Viewer"
                role_id = role_ids[role_name]
                exists = db.execute(
                    text(
                        """
                        SELECT 1 FROM workspace_members
                        WHERE workspace_id = :ws_id AND user_id = :user_id
                        """
                    ),
                    {"ws_id": workspace_id, "user_id": user_id},
                ).first()
                if exists:
                    continue
                db.execute(
                    text(
                        """
                        INSERT INTO workspace_members (id, workspace_id, user_id, role_id)
                        VALUES (gen_random_uuid(), :ws_id, :user_id, CAST(:role_id AS UUID))
                        """
                    ),
                    {
                        "ws_id": workspace_id,
                        "user_id": user_id,
                        "role_id": role_id,
                    },
                )
        print(f"Backfilled workspace memberships for org {org_id}")

    db.commit()
    print("Workspace RBAC schema is in place")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS workspace_members"))
    db.execute(text("DROP TABLE IF EXISTS workspace_roles"))
    db.commit()
