#!/usr/bin/env python3
"""
Script to apply migration 017: Add voice_ai_integration_id and voice_ai_agent_id to agents table
"""
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from sqlalchemy import text
import logging
import importlib

migration_017 = importlib.import_module("migrations.017_add_voice_ai_integration_to_agents")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    db = SessionLocal()
    try:
        logger.info("=" * 60)
        logger.info("Applying migration: Add Voice AI Integration to Agents")
        logger.info("=" * 60)
        
        # Apply the migration using the function from the migration file
        migration_017.upgrade(db)
        
        # Record the migration
        logger.info("Recording migration in schema_migrations...")
        try:
            db.execute(text("""
                INSERT INTO schema_migrations (version, description) 
                VALUES ('017_add_voice_ai_integration_to_agents', 'Add voice_ai_integration_id and voice_ai_agent_id fields to agents table')
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
