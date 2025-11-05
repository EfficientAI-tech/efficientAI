"""
Migration: Add Integrations Support
Adds support for external platform integrations (Retell, Vapi, etc.).
"""

import logging

logger = logging.getLogger(__name__)
description = "Add integrations support for external voice AI platforms"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    # Step 1: Create integrationplatform enum type
    logger.info("  1. Creating integrationplatform enum type...")
    try:
        db.execute(text("""
            DO $$ BEGIN
                CREATE TYPE integrationplatform AS ENUM ('retell', 'vapi');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        db.commit()
        logger.info("     ✓ integrationplatform enum type created")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ integrationplatform enum type may already exist: {e}")
        db.rollback()
    
    # Step 2: Create integrations table
    logger.info("  2. Creating integrations table...")
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS integrations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                platform integrationplatform NOT NULL,
                name VARCHAR(255),
                api_key VARCHAR(255) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                last_tested_at TIMESTAMP WITH TIME ZONE,
                UNIQUE(organization_id, platform, name)
            )
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_integrations_org_id ON integrations(organization_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_integrations_platform ON integrations(platform)"))
        db.commit()
        logger.info("     ✓ integrations table created with indexes and unique constraint")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ integrations table may already exist: {e}")
        db.rollback()
    
    logger.info("  ✓ Migration completed successfully!")

