#!/usr/bin/env python3
"""
Script to apply migration 016: Add first_name and last_name to users table
"""
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from sqlalchemy import text
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    db = SessionLocal()
    try:
        logger.info("=" * 60)
        logger.info("Applying migration: Add first_name and last_name to users")
        logger.info("=" * 60)
        
        # Check if first_name column exists
        logger.info("Checking if first_name column exists...")
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'users' 
            AND column_name = 'first_name'
        """))
        
        if result.fetchone():
            logger.info("  ✓ first_name column already exists, skipping")
        else:
            logger.info("  Adding first_name column...")
            db.execute(text("ALTER TABLE users ADD COLUMN first_name VARCHAR(255)"))
            db.commit()
            logger.info("  ✓ first_name column added")
        
        # Check if last_name column exists
        logger.info("Checking if last_name column exists...")
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'users' 
            AND column_name = 'last_name'
        """))
        
        if result.fetchone():
            logger.info("  ✓ last_name column already exists, skipping")
        else:
            logger.info("  Adding last_name column...")
            db.execute(text("ALTER TABLE users ADD COLUMN last_name VARCHAR(255)"))
            db.commit()
            logger.info("  ✓ last_name column added")
        
        # Record the migration
        logger.info("Recording migration in schema_migrations...")
        try:
            db.execute(text("""
                INSERT INTO schema_migrations (version, description) 
                VALUES ('016_add_first_last_name_to_users', 'Add first_name and last_name columns to users table')
                ON CONFLICT (version) DO NOTHING
            """))
            db.commit()
            logger.info("  ✓ Migration recorded")
        except Exception as e:
            logger.warning(f"  ⚠ Could not record migration (may already be recorded): {e}")
            db.rollback()
        
        logger.info("=" * 60)
        logger.info("✅ Migration completed successfully!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Error applying migration: {e}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()

