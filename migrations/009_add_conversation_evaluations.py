"""
Migration: Add Conversation Evaluations
Adds conversation_evaluations table for evaluating manual transcriptions against agent objectives.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add conversation_evaluations table for evaluating manual transcriptions against agent objectives"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    # Note: modelprovider enum type is already created in migration 004
    
    # 1. Create conversation_evaluations table
    logger.info("  1. Creating conversation_evaluations table...")
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS conversation_evaluations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL,
                transcription_id UUID NOT NULL,
                agent_id UUID NOT NULL,
                objective_achieved BOOLEAN NOT NULL,
                objective_achieved_reason VARCHAR,
                additional_metrics JSON,
                overall_score DOUBLE PRECISION,
                llm_provider modelprovider,
                llm_model VARCHAR(100),
                llm_response JSON,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_conversation_evaluations_organization_id 
                    FOREIGN KEY (organization_id) REFERENCES organizations(id),
                CONSTRAINT fk_conversation_evaluations_transcription_id 
                    FOREIGN KEY (transcription_id) REFERENCES manual_transcriptions(id),
                CONSTRAINT fk_conversation_evaluations_agent_id 
                    FOREIGN KEY (agent_id) REFERENCES agents(id)
            )
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_conversation_evaluations_organization_id ON conversation_evaluations(organization_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_conversation_evaluations_transcription_id ON conversation_evaluations(transcription_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_conversation_evaluations_agent_id ON conversation_evaluations(agent_id)"))
        db.commit()
        logger.info("     ✓ conversation_evaluations table created with indexes")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ conversation_evaluations table may already exist: {e}")
        db.rollback()
    
    logger.info("  ✓ Migration completed successfully!")

