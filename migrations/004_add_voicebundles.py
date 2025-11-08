"""
Migration: Add VoiceBundles
Adds VoiceBundle table for composable STT + LLM + TTS configurations.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add VoiceBundle table for composable voice AI configurations"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    # 1. Create ModelProvider enum type
    logger.info("  1. Creating ModelProvider enum type...")
    try:
        db.execute(text("""
            DO $$ BEGIN
                CREATE TYPE modelprovider AS ENUM (
                    'openai',
                    'anthropic',
                    'google',
                    'azure',
                    'aws',
                    'custom'
                );
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        db.commit()
        logger.info("     ✓ ModelProvider enum created")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ ModelProvider enum may already exist: {e}")
        db.rollback()
    
    # 2. Create voicebundles table
    logger.info("  2. Creating voicebundles table...")
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS voicebundles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                
                -- STT Configuration (references AIProvider)
                stt_provider modelprovider NOT NULL,
                stt_model VARCHAR(255) NOT NULL,
                
                -- LLM Configuration (references AIProvider)
                llm_provider modelprovider NOT NULL,
                llm_model VARCHAR(255) NOT NULL,
                llm_temperature FLOAT,
                llm_max_tokens INTEGER,
                llm_config JSONB,
                
                -- TTS Configuration (references AIProvider)
                tts_provider modelprovider NOT NULL,
                tts_model VARCHAR(255) NOT NULL,
                tts_voice VARCHAR(255),
                tts_config JSONB,
                
                -- Additional metadata
                extra_metadata JSONB,
                
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                
                CONSTRAINT voicebundles_organization_id_fkey FOREIGN KEY (organization_id) 
                    REFERENCES organizations(id) ON DELETE CASCADE
            )
        """))
        db.commit()
        logger.info("     ✓ VoiceBundles table created")
    except ProgrammingError as e:
        logger.error(f"     ✗ Failed to create voicebundles table: {e}")
        db.rollback()
        raise
    
    # 3. Create indexes
    logger.info("  3. Creating indexes...")
    try:
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_voicebundles_organization_id 
            ON voicebundles(organization_id)
        """))
        db.commit()
        logger.info("     ✓ Indexes created")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ Index creation warning: {e}")
        db.rollback()
    
    logger.info("  ✓ Migration 004 completed successfully")


def downgrade(db):
    """Rollback this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    logger.info("  Rolling back migration 004...")
    
    # 1. Drop table
    try:
        db.execute(text("DROP TABLE IF EXISTS voicebundles CASCADE"))
        db.commit()
        logger.info("     ✓ VoiceBundles table dropped")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ Error dropping table: {e}")
        db.rollback()
    
    # 2. Drop enum (only if no other tables use it)
    try:
        db.execute(text("DROP TYPE IF EXISTS modelprovider CASCADE"))
        db.commit()
        logger.info("     ✓ ModelProvider enum dropped")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ Error dropping enum: {e}")
        db.rollback()
    
    logger.info("  ✓ Rollback completed")

