"""
Migration: Add speaker_segments column to evaluator_results table
"""

import logging

logger = logging.getLogger(__name__)
description = "Add speaker_segments column to evaluator_results table"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    
    logger.info("Adding speaker_segments column to evaluator_results table...")
    
    try:
        # Check if column already exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'evaluator_results' 
            AND column_name = 'speaker_segments'
        """))
        
        if result.fetchone():
            logger.info("  ✓ speaker_segments column already exists, skipping")
            return
        
        # Add speaker_segments column
        logger.info("  Adding speaker_segments column...")
        db.execute(text("""
            ALTER TABLE evaluator_results 
            ADD COLUMN speaker_segments JSONB
        """))
        db.commit()
        logger.info("  ✓ speaker_segments column added")
        
    except Exception as e:
        db.rollback()
        logger.error(f"  ✗ Error adding speaker_segments column: {e}")
        raise

def downgrade(db):
    """Rollback this migration."""
    from sqlalchemy import text
    
    logger.info("Removing speaker_segments column from evaluator_results table...")
    
    try:
        db.execute(text("""
            ALTER TABLE evaluator_results 
            DROP COLUMN IF EXISTS speaker_segments
        """))
        db.commit()
        logger.info("  ✓ speaker_segments column removed")
    except Exception as e:
        db.rollback()
        logger.error(f"  ✗ Error removing speaker_segments column: {e}")
        raise

