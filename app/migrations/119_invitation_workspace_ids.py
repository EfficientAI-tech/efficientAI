"""Scope invitations to explicit workspace ids."""

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add invitations.workspace_ids and backfill pending invites"
MIGRATION_SCOPE = "catalog"


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _table_exists(db, "invitations"):
        db.commit()
        return
    if not _column_exists(db, "invitations", "workspace_ids"):
        db.execute(
            text(
                """
                ALTER TABLE invitations
                ADD COLUMN workspace_ids JSONB NOT NULL DEFAULT '[]'::jsonb
                """
            )
        )

    pending_rows = db.execute(
        text(
            """
            SELECT i.id, i.organization_id
            FROM invitations i
            WHERE i.status = 'pending'
            """
        )
    ).fetchall()
    for row in pending_rows:
        inv_id, org_id = row[0], row[1]
        ws_rows = db.execute(
            text(
                """
                SELECT id::text
                FROM workspaces
                WHERE organization_id = :org_id
                  AND is_active IS NOT FALSE
                ORDER BY is_default DESC, name ASC
                """
            ),
            {"org_id": str(org_id)},
        ).fetchall()
        ws_ids = [ws_row[0] for ws_row in ws_rows]
        db.execute(
            text(
                """
                UPDATE invitations
                SET workspace_ids = CAST(:ws_ids AS jsonb)
                WHERE id = :inv_id
                """
            ),
            {"ws_ids": json.dumps(ws_ids), "inv_id": str(inv_id)},
        )
    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "invitations"):
        db.commit()
        return
    if _column_exists(db, "invitations", "workspace_ids"):
        db.execute(text("ALTER TABLE invitations DROP COLUMN workspace_ids"))
    db.commit()
