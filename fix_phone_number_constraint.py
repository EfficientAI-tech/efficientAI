#!/usr/bin/env python3
"""
Quick fix script to make phone_number nullable in agents table.
This fixes the IntegrityError when creating agents with WEB_CALL medium.
"""

import sys
import traceback
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

def fix_phone_number_constraint():
    """Make phone_number column nullable in agents table."""
    try:
        from app.database import SessionLocal
    except ImportError as e:
        print(f"❌ Failed to import database module: {e}")
        print("   Make sure you're running this from the project root directory")
        return False
    
    db = SessionLocal()
    try:
        print("🔧 Fixing phone_number constraint in agents table...")
        print("   Connecting to database...")
        
        # Check current state
        print("   Checking current column state...")
        result = db.execute(text("""
            SELECT is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'agents' 
            AND column_name = 'phone_number'
        """))
        row = result.fetchone()
        
        if not row:
            print("❌ phone_number column not found in agents table")
            return False
        
        is_nullable = row[0]
        if is_nullable == 'YES':
            print("✅ phone_number column is already nullable - no changes needed")
            return True
        
        print(f"   Current state: phone_number is NOT NULL")
        print("   Making it nullable...")
        
        # Drop NOT NULL constraint
        db.execute(text("ALTER TABLE agents ALTER COLUMN phone_number DROP NOT NULL"))
        db.commit()
        print("   ✓ ALTER TABLE command executed")
        
        # Verify the change
        print("   Verifying the change...")
        result = db.execute(text("""
            SELECT is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'agents' 
            AND column_name = 'phone_number'
        """))
        row = result.fetchone()
        
        if row and row[0] == 'YES':
            print("✅ Successfully made phone_number nullable!")
            print("   You can now create agents with WEB_CALL medium without phone_number")
            return True
        else:
            print("❌ Failed to make phone_number nullable - verification failed")
            return False
            
    except SQLAlchemyError as e:
        print(f"❌ Database error: {e}")
        print(f"   Error details: {traceback.format_exc()}")
        db.rollback()
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        print(f"   Error details: {traceback.format_exc()}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("Fix phone_number Constraint Script")
    print("=" * 60)
    success = fix_phone_number_constraint()
    print("=" * 60)
    sys.exit(0 if success else 1)

