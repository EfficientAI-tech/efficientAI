"""
Database migration system that runs automatically on application startup.
Migrations are tracked in a `schema_migrations` table to ensure they only run once.
"""

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session
from sqlalchemy.exc import ProgrammingError
from app.database import engine, SessionLocal, Base
import logging

logger = logging.getLogger(__name__)

# Get migrations directory
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


class MigrationRunner:
    """Handles running database migrations in order."""
    
    def __init__(self, db: Session):
        self.db = db
        self.ensure_migrations_table()
    
    def ensure_migrations_table(self):
        """Create the schema_migrations table if it doesn't exist."""
        try:
            self.db.execute(text("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """))
            self.db.commit()
            logger.info("Schema migrations table ready")
        except Exception as e:
            logger.error(f"Error creating migrations table: {e}")
            self.db.rollback()
            raise
    
    def get_applied_migrations(self) -> List[str]:
        """Get list of already applied migration versions."""
        try:
            result = self.db.execute(text("SELECT version FROM schema_migrations ORDER BY version"))
            return [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching applied migrations: {e}")
            return []
    
    def record_migration(self, version: str, description: str):
        """Record that a migration has been applied."""
        try:
            self.db.execute(
                text("INSERT INTO schema_migrations (version, description) VALUES (:version, :description)"),
                {"version": version, "description": description}
            )
            self.db.commit()
            logger.info(f"Recorded migration: {version}")
        except Exception as e:
            logger.error(f"Error recording migration: {e}")
            self.db.rollback()
            raise
    
    def get_pending_migrations(self) -> List[Path]:
        """Get list of migration files that haven't been applied yet."""
        if not MIGRATIONS_DIR.exists():
            logger.warning(f"Migrations directory does not exist: {MIGRATIONS_DIR}")
            return []
        
        applied = set(self.get_applied_migrations())
        pending = []
        
        # Get all Python files in migrations directory, sorted by name
        migration_files = sorted(MIGRATIONS_DIR.glob("*.py"))
        
        for migration_file in migration_files:
            version = migration_file.stem  # filename without .py
            if version not in applied and not version.startswith("__"):
                pending.append(migration_file)
        
        return pending
    
    def run_migration(self, migration_file: Path) -> bool:
        """Run a single migration file."""
        version = migration_file.stem
        logger.info(f"Running migration: {version}")
        
        try:
            # Use importlib to handle module names starting with numbers
            import importlib.util
            spec = importlib.util.spec_from_file_location(f"migrations_{version}", migration_file)
            if spec is None or spec.loader is None:
                logger.error(f"Could not load migration file: {migration_file}")
                return False
            
            migration_module = importlib.util.module_from_spec(spec)
            sys.modules[f"migrations_{version}"] = migration_module
            spec.loader.exec_module(migration_module)
            
            # Check if migration has upgrade function
            if not hasattr(migration_module, "upgrade"):
                logger.error(f"Migration {version} does not have an 'upgrade' function")
                return False
            
            # Run the migration
            migration_module.upgrade(self.db)
            
            # Record the migration
            description = getattr(migration_module, "description", "No description")
            self.record_migration(version, description)
            
            logger.info(f"Successfully applied migration: {version}")
            return True
            
        except Exception as e:
            import traceback
            logger.error(f"Error running migration {version}: {e}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            self.db.rollback()
            return False
        finally:
            # Clean up
            if f"migrations_{version}" in sys.modules:
                del sys.modules[f"migrations_{version}"]
    
    def run_all(self) -> bool:
        """Run all pending migrations."""
        pending = self.get_pending_migrations()
        
        if not pending:
            logger.info("✅ No pending migrations - database is up to date")
            return True
        
        logger.info(f"📋 Found {len(pending)} pending migration(s):")
        for migration_file in pending:
            logger.info(f"   - {migration_file.name}")
        
        success = True
        
        for migration_file in pending:
            logger.info("")
            logger.info(f"🔄 Applying migration: {migration_file.name}")
            if not self.run_migration(migration_file):
                logger.error(f"❌ Failed to run migration: {migration_file.name}")
                success = False
                break  # Stop on first failure
            else:
                logger.info(f"✅ Successfully applied: {migration_file.name}")
        
        if success:
            logger.info("")
            logger.info("✅ All pending migrations completed successfully")
        
        return success


def run_migrations():
    """
    Run all pending database migrations.
    This should be called on application startup.
    
    Raises:
        RuntimeError: If migrations fail, preventing application startup
    """
    # Ensure logging is configured at INFO level
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True
    )
    
    logger.info("=" * 60)
    logger.info("🔄 Starting database migrations...")
    logger.info("=" * 60)
    
    db = SessionLocal()
    try:
        runner = MigrationRunner(db)
        
        # Check current migration status
        applied = runner.get_applied_migrations()
        pending = runner.get_pending_migrations()
        
        if applied:
            logger.info(f"📊 Currently applied migrations: {len(applied)}")
            for version in applied[-5:]:  # Show last 5
                logger.info(f"   ✓ {version}")
            if len(applied) > 5:
                logger.info(f"   ... and {len(applied) - 5} more")
        
        if not pending:
            logger.info("✅ Database is up to date - no migrations needed")
            return
        
        # Run migrations
        success = runner.run_all()
        if not success:
            logger.error("")
            logger.error("=" * 60)
            logger.error("❌ MIGRATION FAILED - Application cannot start!")
            logger.error("=" * 60)
            logger.error("The application will not start until migrations succeed.")
            logger.error("")
            logger.error("To diagnose the issue:")
            logger.error("  1. Run: eai migrate --verbose")
            logger.error("  2. Check the error messages above")
            logger.error("  3. Fix any database schema issues")
            logger.error("=" * 60)
            raise RuntimeError("Database migrations failed")
        
        # Verify migrations were applied
        logger.info("")
        logger.info("🔍 Verifying migrations were applied...")
        final_pending = runner.get_pending_migrations()
        if final_pending:
            logger.warning(f"⚠️  Warning: {len(final_pending)} migration(s) still pending after run:")
            for migration_file in final_pending:
                logger.warning(f"   - {migration_file.name}")
            logger.warning("This may indicate a migration tracking issue.")
        else:
            logger.info("✅ Verification complete - all migrations applied successfully")
        
        logger.info("=" * 60)
        
    except RuntimeError:
        # Re-raise RuntimeError (migration failures)
        raise
    except Exception as e:
        logger.error("")
        logger.error("=" * 60)
        logger.error("❌ UNEXPECTED ERROR during migrations!")
        logger.error("=" * 60)
        logger.error(f"Error: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        logger.error("=" * 60)
        raise
    finally:
        db.close()


def check_migrations_status() -> Tuple[bool, List[str]]:
    """
    Check if there are any pending migrations.
    
    Returns:
        Tuple of (is_up_to_date, pending_migration_names)
        - is_up_to_date: True if all migrations are applied
        - pending_migration_names: List of pending migration file names
    """
    try:
        db = SessionLocal()
        try:
            runner = MigrationRunner(db)
            pending = runner.get_pending_migrations()
            pending_names = [m.stem for m in pending]
            return (len(pending) == 0, pending_names)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error checking migration status: {e}")
        # If we can't check, assume migrations are needed (fail safe)
        return (False, ["unknown"])


def ensure_migrations_directory():
    """Ensure the migrations directory exists."""
    MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Create __init__.py if it doesn't exist
    init_file = MIGRATIONS_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text("# Migrations package\n")

