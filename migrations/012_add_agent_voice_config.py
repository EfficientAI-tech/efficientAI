"""
Migration: Add Voice Configuration to Agents
Adds voice_bundle_id and ai_provider_id fields to agents table for voice configuration.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add voice_bundle_id and ai_provider_id to agents table"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    # 1. Add voice_bundle_id column
    logger.info("  1. Adding voice_bundle_id column to agents table...")
    try:
        db.execute(text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS voice_bundle_id UUID"))
        db.commit()
        logger.info("  ✓ voice_bundle_id column added")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower() or "column" in str(e).lower() and "already exists" in str(e).lower():
            logger.info("  ✓ voice_bundle_id column already exists, skipping")
        else:
            raise
    
    # 1b. Add foreign key constraint for voice_bundle_id
    logger.info("  1b. Adding foreign key constraint for voice_bundle_id...")
    try:
        db.execute(text("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'fk_agents_voice_bundle_id'
                ) THEN
                    ALTER TABLE agents 
                    ADD CONSTRAINT fk_agents_voice_bundle_id 
                        FOREIGN KEY (voice_bundle_id) REFERENCES voicebundles(id);
                END IF;
            END $$;
        """))
        db.commit()
        logger.info("  ✓ Foreign key constraint added for voice_bundle_id")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.info("  ✓ Foreign key constraint already exists, skipping")
        else:
            raise
    
    # 2. Add ai_provider_id column
    logger.info("  2. Adding ai_provider_id column to agents table...")
    try:
        db.execute(text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS ai_provider_id UUID"))
        db.commit()
        logger.info("  ✓ ai_provider_id column added")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower() or "column" in str(e).lower() and "already exists" in str(e).lower():
            logger.info("  ✓ ai_provider_id column already exists, skipping")
        else:
            raise
    
    # 2b. Add foreign key constraint for ai_provider_id
    logger.info("  2b. Adding foreign key constraint for ai_provider_id...")
    try:
        db.execute(text("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'fk_agents_ai_provider_id'
                ) THEN
                    ALTER TABLE agents 
                    ADD CONSTRAINT fk_agents_ai_provider_id 
                        FOREIGN KEY (ai_provider_id) REFERENCES aiproviders(id);
                END IF;
            END $$;
        """))
        db.commit()
        logger.info("  ✓ Foreign key constraint added for ai_provider_id")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.info("  ✓ Foreign key constraint already exists, skipping")
        else:
            raise
    
    # 3. Create indexes
    logger.info("  3. Creating indexes...")
    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_agents_voice_bundle_id ON agents(voice_bundle_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_agents_ai_provider_id ON agents(ai_provider_id)"))
        db.commit()
        logger.info("  ✓ Indexes created")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower():
            logger.info("  ✓ Indexes already exist, skipping")
        else:
            raise

def downgrade(db):
    """Rollback this migration."""
    from sqlalchemy import text
    
    logger.info("  Removing voice configuration columns from agents table...")
    db.execute(text("ALTER TABLE agents DROP COLUMN IF EXISTS ai_provider_id CASCADE"))
    db.execute(text("ALTER TABLE agents DROP COLUMN IF EXISTS voice_bundle_id CASCADE"))
    db.commit()
    logger.info("  ✓ Columns removed")

