"""
Migration: add refresh_tokens table for session refresh and logout revocation.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add refresh_tokens table for auth session management"


def upgrade(db: Session):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            revoked_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """))
    db.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_refresh_tokens_token_hash
            ON refresh_tokens (token_hash)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_id
            ON refresh_tokens (user_id)
    """))
    db.commit()
    print("Added refresh_tokens table")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS refresh_tokens"))
    db.commit()
    print("Dropped refresh_tokens table")
