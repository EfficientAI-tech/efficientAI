"""
Migration: Add first_name and last_name columns to users table
Adds first_name and last_name columns to support separate first and last name fields.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add first_name and last_name columns to users table"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    
    logger.info("Adding first_name and last_name columns to users table...")
    
    try:
        # Check if first_name column already exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'users' 
            AND column_name = 'first_name'
        """))
        
        if result.fetchone():
            logger.info("  ✓ first_name column already exists, skipping")
        else:
            # Add first_name column
            logger.info("  Adding first_name column...")
            db.execute(text("""
                ALTER TABLE users 
                ADD COLUMN first_name VARCHAR(255)
            """))
            logger.info("  ✓ first_name column added")
        
        # Check if last_name column already exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'users' 
            AND column_name = 'last_name'
        """))
        
        if result.fetchone():
            logger.info("  ✓ last_name column already exists, skipping")
        else:
            # Add last_name column
            logger.info("  Adding last_name column...")
            db.execute(text("""
                ALTER TABLE users 
                ADD COLUMN last_name VARCHAR(255)
            """))
            logger.info("  ✓ last_name column added")
        
        db.commit()
        logger.info("  ✓ Migration completed successfully")
        
    except Exception as e:
        db.rollback()
        logger.error(f"  ✗ Error adding columns: {e}")
        raise

def downgrade(db):
    """Rollback this migration."""
    from sqlalchemy import text
    
    logger.info("Removing first_name and last_name columns from users table...")
    
    try:
        # Remove first_name column
        logger.info("  Removing first_name column...")
        db.execute(text("""
            ALTER TABLE users 
            DROP COLUMN IF EXISTS first_name
        """))
        logger.info("  ✓ first_name column removed")
        
        # Remove last_name column
        logger.info("  Removing last_name column...")
        db.execute(text("""
            ALTER TABLE users 
            DROP COLUMN IF EXISTS last_name
        """))
        logger.info("  ✓ last_name column removed")
        
        db.commit()
        logger.info("  ✓ Rollback completed successfully")
    except Exception as e:
        db.rollback()
        logger.error(f"  ✗ Error removing columns: {e}")
        raise

