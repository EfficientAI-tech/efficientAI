#!/usr/bin/env python3
"""
Quick script to add the name column to manual_transcriptions table.
Run this if the migration hasn't run yet.
"""

import sys
import os
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from app.database import SessionLocal

def add_name_column():
    """Add name column to manual_transcriptions table."""
    db = SessionLocal()
    try:
        print("Checking if name column exists...")
        
        # Check if column exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'manual_transcriptions' 
            AND column_name = 'name'
        """))
        
        if result.fetchone():
            print("✓ name column already exists!")
            return True
        
        print("Adding name column...")
        # Add the column
        db.execute(text("""
            ALTER TABLE manual_transcriptions 
            ADD COLUMN name VARCHAR(255)
        """))
        db.commit()
        print("✓ Successfully added name column to manual_transcriptions table!")
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = add_name_column()
    sys.exit(0 if success else 1)

