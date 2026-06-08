"""Migration: Backfill Default workspace for organizations missing one."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Seed a Default workspace for any organization that does not yet have one."
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


def upgrade(db: Session):
    if not _table_exists(db, "workspaces"):
        print("workspaces table does not exist, skipping backfill")
        db.commit()
        return

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
    db.commit()
    print("Backfilled Default workspace for organizations missing one")


def downgrade(db: Session):
    # No-op: cannot safely distinguish backfilled defaults from user-created ones.
    db.commit()
