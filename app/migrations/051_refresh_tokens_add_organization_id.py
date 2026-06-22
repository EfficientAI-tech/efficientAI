"""
Migration: add organization_id to refresh_tokens.

Migration 050 used CREATE TABLE IF NOT EXISTS, so databases that already had
an earlier refresh_tokens shape were not upgraded automatically.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add organization_id to refresh_tokens for org-scoped refresh"


def upgrade(db: Session):
    db.execute(text("""
        ALTER TABLE refresh_tokens
            ADD COLUMN IF NOT EXISTS organization_id UUID
                REFERENCES organizations(id) ON DELETE CASCADE
    """))
    db.execute(text("""
        UPDATE refresh_tokens rt
        SET organization_id = sub.organization_id
        FROM (
            SELECT DISTINCT ON (om.user_id)
                om.user_id,
                om.organization_id
            FROM organization_members om
            ORDER BY om.user_id, om.joined_at ASC
        ) sub
        WHERE rt.user_id = sub.user_id
          AND rt.organization_id IS NULL
    """))
    db.execute(text("""
        DELETE FROM refresh_tokens
        WHERE organization_id IS NULL
    """))
    db.execute(text("""
        ALTER TABLE refresh_tokens
            ALTER COLUMN organization_id SET NOT NULL
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_refresh_tokens_organization_id
            ON refresh_tokens (organization_id)
    """))
    db.commit()
    print("Added organization_id to refresh_tokens")


def downgrade(db: Session):
    db.execute(text("""
        DROP INDEX IF EXISTS ix_refresh_tokens_organization_id
    """))
    db.execute(text("""
        ALTER TABLE refresh_tokens
            DROP COLUMN IF EXISTS organization_id
    """))
    db.commit()
    print("Removed organization_id from refresh_tokens")
