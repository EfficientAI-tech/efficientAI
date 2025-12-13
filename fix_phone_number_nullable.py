#!/usr/bin/env python3
"""Fix phone_number column to be nullable"""

from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    # Check current state
    result = db.execute(text("""
        SELECT is_nullable 
        FROM information_schema.columns 
        WHERE table_name = 'agents' AND column_name = 'phone_number'
    """)).fetchone()
    
    if result:
        print(f"Current phone_number nullable status: {result[0]}")
        
        if result[0] == 'NO':
            print("Making phone_number nullable...")
            db.execute(text("ALTER TABLE agents ALTER COLUMN phone_number DROP NOT NULL"))
            db.commit()
            print("✅ phone_number is now nullable")
            
            # Verify
            result = db.execute(text("""
                SELECT is_nullable 
                FROM information_schema.columns 
                WHERE table_name = 'agents' AND column_name = 'phone_number'
            """)).fetchone()
            print(f"Verified: phone_number nullable status is now: {result[0]}")
        else:
            print("phone_number is already nullable")
    else:
        print("ERROR: phone_number column not found!")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    db.rollback()
finally:
    db.close()

