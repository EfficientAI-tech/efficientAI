"""
Migration: Add persona ambient noise configuration columns.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add persona background noise source, preset, volume, and s3 key"


def upgrade(db: Session):
    db.execute(text("""
        ALTER TABLE personas
            ADD COLUMN IF NOT EXISTS background_noise_source VARCHAR(20) NOT NULL DEFAULT 'none',
            ADD COLUMN IF NOT EXISTS background_noise_preset VARCHAR(50),
            ADD COLUMN IF NOT EXISTS background_noise_volume DOUBLE PRECISION DEFAULT 0.22,
            ADD COLUMN IF NOT EXISTS background_noise_s3_key VARCHAR
    """))
    db.commit()
    print("Added persona ambient noise columns")


def downgrade(db: Session):
    db.execute(text("""
        ALTER TABLE personas
            DROP COLUMN IF EXISTS background_noise_s3_key,
            DROP COLUMN IF EXISTS background_noise_volume,
            DROP COLUMN IF EXISTS background_noise_preset,
            DROP COLUMN IF EXISTS background_noise_source
    """))
    db.commit()
    print("Dropped persona ambient noise columns")
