"""
Migration: Add AI Providers
Adds AIProvider table for managing API keys for different AI platforms.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add AIProvider table for managing AI platform API keys"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    # 1. Create aiproviders table
    logger.info("  1. Creating aiproviders table...")
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS aiproviders (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                provider modelprovider NOT NULL,
                api_key VARCHAR(255) NOT NULL,
                name VARCHAR(255),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                last_tested_at TIMESTAMP WITH TIME ZONE,
                
                CONSTRAINT unique_org_provider UNIQUE (organization_id, provider),
                CONSTRAINT aiproviders_organization_id_fkey FOREIGN KEY (organization_id) 
                    REFERENCES organizations(id) ON DELETE CASCADE
            )
        """))
        db.commit()
        logger.info("     ✓ AIProviders table created")
    except ProgrammingError as e:
        logger.error(f"     ✗ Failed to create aiproviders table: {e}")
        db.rollback()
        raise
    
    # 2. Create indexes
    logger.info("  2. Creating indexes...")
    try:
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_aiproviders_organization_id 
            ON aiproviders(organization_id)
        """))
        db.commit()
        logger.info("     ✓ Indexes created")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ Index creation warning: {e}")
        db.rollback()
    
    logger.info("  ✓ Migration 005 completed successfully")


def downgrade(db):
    """Rollback this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    logger.info("  Rolling back migration 005...")
    
    # 1. Drop table
    try:
        db.execute(text("DROP TABLE IF EXISTS aiproviders CASCADE"))
        db.commit()
        logger.info("     ✓ AIProviders table dropped")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ Error dropping table: {e}")
        db.rollback()
    
    logger.info("  ✓ Rollback completed")

