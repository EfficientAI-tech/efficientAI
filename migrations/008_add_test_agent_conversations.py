"""
Migration: Add Test Agent Conversations
Adds TestAgentConversation table for managing conversations between test AI agent and voice AI agent.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add TestAgentConversation table for test agent conversations"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    # 1. Create TestAgentConversationStatus enum type
    logger.info("  1. Creating TestAgentConversationStatus enum type...")
    try:
        db.execute(text("""
            DO $$ BEGIN
                CREATE TYPE testagentconversationstatus AS ENUM (
                    'initializing',
                    'active',
                    'paused',
                    'completed',
                    'failed',
                    'cancelled'
                );
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        db.commit()
        logger.info("     ✓ TestAgentConversationStatus enum created")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ TestAgentConversationStatus enum may already exist: {e}")
        db.rollback()
    
    # 2. Create test_agent_conversations table
    logger.info("  2. Creating test_agent_conversations table...")
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS test_agent_conversations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                
                -- Configuration
                agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                persona_id UUID NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
                scenario_id UUID NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
                voice_bundle_id UUID NOT NULL REFERENCES voicebundles(id) ON DELETE CASCADE,
                
                -- Conversation data
                status testagentconversationstatus NOT NULL DEFAULT 'initializing',
                live_transcription JSONB,
                conversation_audio_key VARCHAR(512),
                full_transcript TEXT,
                
                -- Metadata
                started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP WITH TIME ZONE,
                duration_seconds FLOAT,
                conversation_metadata JSONB,
                
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255)
            );
        """))
        db.commit()
        logger.info("     ✓ test_agent_conversations table created")
    except ProgrammingError as e:
        logger.error(f"     ✗ Failed to create test_agent_conversations table: {e}")
        db.rollback()
        raise
    
    # 3. Create indexes
    logger.info("  3. Creating indexes...")
    try:
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_test_agent_conversations_organization_id 
            ON test_agent_conversations(organization_id);
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_test_agent_conversations_agent_id 
            ON test_agent_conversations(agent_id);
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_test_agent_conversations_status 
            ON test_agent_conversations(status);
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_test_agent_conversations_created_at 
            ON test_agent_conversations(created_at DESC);
        """))
        db.commit()
        logger.info("     ✓ Indexes created")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ Some indexes may already exist: {e}")
        db.rollback()
    
    logger.info("  ✓ Migration 008 completed successfully")


def downgrade(db):
    """Rollback this migration."""
    from sqlalchemy import text
    
    logger.info("  Rolling back migration 008...")
    
    # Drop table
    try:
        db.execute(text("DROP TABLE IF EXISTS test_agent_conversations CASCADE"))
        db.commit()
        logger.info("     ✓ test_agent_conversations table dropped")
    except Exception as e:
        logger.warning(f"     ⚠ Error dropping table: {e}")
        db.rollback()
    
    # Drop enum type
    try:
        db.execute(text("DROP TYPE IF EXISTS testagentconversationstatus"))
        db.commit()
        logger.info("     ✓ TestAgentConversationStatus enum dropped")
    except Exception as e:
        logger.warning(f"     ⚠ Error dropping enum: {e}")
        db.rollback()
    
    logger.info("  ✓ Rollback completed")

