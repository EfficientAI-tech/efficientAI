"""
Migration: add auth-related columns to users.

Introduces:
  - external_id   - stable subject from the upstream IdP (e.g. "keycloak:<sub>")
  - auth_provider - which provider first created this user ("local", "keycloak", ...)
  - mfa_enabled   - has the user completed MFA enrolment?
  - last_login_at - wall-clock of the most recent successful interactive sign-in

These columns are all nullable/default-safe so API-key-only deployments are
unaffected. They are indexed on external_id for the O(1) lookup performed on
every OIDC login.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add external_id, auth_provider, mfa_enabled, last_login_at to users"


def upgrade(db: Session):
    db.execute(text("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS external_id VARCHAR(255),
            ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(50),
            ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP WITH TIME ZONE
    """))
    db.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_external_id
            ON users (external_id)
            WHERE external_id IS NOT NULL
    """))
    db.commit()
    print("Added auth columns (external_id, auth_provider, mfa_enabled, last_login_at) to users")


def downgrade(db: Session):
    db.execute(text("""
        DROP INDEX IF EXISTS uq_users_external_id
    """))
    db.execute(text("""
        ALTER TABLE users
            DROP COLUMN IF EXISTS external_id,
            DROP COLUMN IF EXISTS auth_provider,
            DROP COLUMN IF EXISTS mfa_enabled,
            DROP COLUMN IF EXISTS last_login_at
    """))
    db.commit()
    print("Removed auth columns from users")
