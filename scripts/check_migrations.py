"""Script to check migration status and diagnose database schema issues."""

import sys
from pathlib import Path
from sqlalchemy import text, inspect
from app.database import SessionLocal, engine
from app.core.migrations import MigrationRunner

def check_migration_status():
    """Check which migrations have been applied and diagnose issues."""
    print("🔍 Checking database migration status...\n")
    
    db = SessionLocal()
    try:
        runner = MigrationRunner(db)
        
        # Get applied migrations
        applied = runner.get_applied_migrations()
        print(f"✅ Applied migrations ({len(applied)}):")
        if applied:
            for version in applied:
                result = db.execute(
                    text("SELECT description, applied_at FROM schema_migrations WHERE version = :version"),
                    {"version": version}
                )
                row = result.fetchone()
                if row:
                    print(f"   - {version}: {row[0]} (applied at {row[1]})")
                else:
                    print(f"   - {version}")
        else:
            print("   (none)")
        
        # Get pending migrations
        pending = runner.get_pending_migrations()
        print(f"\n⏳ Pending migrations ({len(pending)}):")
        if pending:
            for migration_file in pending:
                print(f"   - {migration_file.name}")
        else:
            print("   (none - all migrations applied)")
        
        # Check for schema issues
        print("\n🔍 Checking database schema...")
        inspector = inspect(engine)
        
        # Check if api_keys table exists and has organization_id
        if 'api_keys' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('api_keys')]
            print(f"\n📋 api_keys table columns: {', '.join(columns)}")
            
            if 'organization_id' not in columns:
                print("   ⚠️  WARNING: api_keys table is missing 'organization_id' column!")
                print("   💡 Solution: Run migrations manually with 'eai migrate'")
                return False
            else:
                print("   ✅ api_keys table has organization_id column")
        else:
            print("   ⚠️  WARNING: api_keys table does not exist!")
            return False
        
        # Check if organizations table exists
        if 'organizations' in inspector.get_table_names():
            print("   ✅ organizations table exists")
        else:
            print("   ⚠️  WARNING: organizations table does not exist!")
            return False
        
        print("\n✅ Database schema looks good!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error checking migrations: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = check_migration_status()
    sys.exit(0 if success else 1)

