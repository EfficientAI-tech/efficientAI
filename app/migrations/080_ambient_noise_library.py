"""
Migration: Add reusable ambient noise library and persona asset reference.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add ambient_noise_assets table and persona background_noise_asset_id"


def upgrade(db: Session):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS ambient_noise_assets (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id),
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
            name VARCHAR(255) NOT NULL,
            s3_key VARCHAR NOT NULL,
            original_filename VARCHAR(255),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_ambient_noise_assets_organization_id
            ON ambient_noise_assets (organization_id)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_ambient_noise_assets_workspace_id
            ON ambient_noise_assets (workspace_id)
    """))
    db.execute(text("""
        ALTER TABLE personas
            ADD COLUMN IF NOT EXISTS background_noise_asset_id UUID
                REFERENCES ambient_noise_assets(id) ON DELETE SET NULL
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_personas_background_noise_asset_id
            ON personas (background_noise_asset_id)
    """))
    db.commit()
    print("Added ambient_noise_assets table and persona background_noise_asset_id")


def downgrade(db: Session):
    db.execute(text("""
        ALTER TABLE personas
            DROP COLUMN IF EXISTS background_noise_asset_id
    """))
    db.execute(text("DROP TABLE IF EXISTS ambient_noise_assets"))
    db.commit()
    print("Dropped ambient_noise_assets table and persona background_noise_asset_id")
