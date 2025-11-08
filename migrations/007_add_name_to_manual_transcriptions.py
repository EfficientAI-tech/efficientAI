"""
Migration: Add name field to Manual Transcriptions
Adds name field to manual_transcriptions table for user-friendly naming.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add name field to manual_transcriptions table"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    logger.info("  1. Adding name column to manual_transcriptions table...")
    try:
        # Check if column already exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'manual_transcriptions' 
            AND column_name = 'name'
        """))
        
        if result.fetchone():
            logger.info("     ✓ name column already exists, skipping")
        else:
            # Add the column
            db.execute(text("""
                ALTER TABLE manual_transcriptions 
                ADD COLUMN name VARCHAR(255)
            """))
            db.commit()
            logger.info("     ✓ name column added to manual_transcriptions table")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ Error adding name column: {e}")
        db.rollback()
        # Try to continue - column might already exist
        try:
            db.execute(text("SELECT name FROM manual_transcriptions LIMIT 1"))
            logger.info("     ✓ name column appears to exist, continuing")
        except:
            raise
    
    logger.info("  ✓ Migration completed successfully!")

