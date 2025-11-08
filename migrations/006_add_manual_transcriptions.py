"""
Migration: Add Manual Transcriptions
Adds manual_transcriptions table for storing transcriptions from S3 audio files.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add manual_transcriptions table for storing transcriptions from S3 audio files"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    # Note: modelprovider enum type is already created in migration 004
    
    # 1. Create manual_transcriptions table
    logger.info("  1. Creating manual_transcriptions table...")
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS manual_transcriptions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL,
                audio_file_key VARCHAR(512) NOT NULL,
                transcript TEXT NOT NULL,
                speaker_segments JSON,
                stt_model VARCHAR(100),
                stt_provider modelprovider,
                language VARCHAR(10),
                processing_time DOUBLE PRECISION,
                raw_output JSON,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_manual_transcriptions_organization_id 
                    FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_manual_transcriptions_organization_id ON manual_transcriptions(organization_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_manual_transcriptions_audio_file_key ON manual_transcriptions(audio_file_key)"))
        db.commit()
        logger.info("     ✓ manual_transcriptions table created with indexes")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ manual_transcriptions table may already exist: {e}")
        db.rollback()
    
    logger.info("  ✓ Migration completed successfully!")

