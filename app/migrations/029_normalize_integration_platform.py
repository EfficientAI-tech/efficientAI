"""
Migration 029: Normalize platform values to lowercase in integrations table

This migration converts uppercase platform values (RETELL, VAPI, DEEPGRAM, etc.)
to their lowercase equivalents to match the IntegrationPlatform enum values.
"""

from sqlalchemy import text

description = "Normalize platform values to lowercase in integrations table"


def upgrade(db):
    """Convert platform column to VARCHAR and normalize to lowercase."""
    
    # Check column data type
    result = db.execute(text("""
        SELECT data_type, udt_name 
        FROM information_schema.columns 
        WHERE table_name = 'integrations' 
        AND column_name = 'platform'
    """))
    row = result.fetchone()
    
    if row:
        data_type, udt_name = row
        
        # If it's an enum (USER-DEFINED), convert to VARCHAR
        if data_type == 'USER-DEFINED' or 'platform' in udt_name.lower():
            print(f"Converting platform from enum to VARCHAR...")
            db.execute(text("""
                ALTER TABLE integrations 
                ALTER COLUMN platform TYPE VARCHAR(50) 
                USING platform::text
            """))
        
        # Now normalize to lowercase
        db.execute(text("""
            UPDATE integrations 
            SET platform = LOWER(platform::text) 
            WHERE platform IS NOT NULL
        """))
    
    print("Normalized platform values in integrations table")
    db.commit()


def downgrade(db):
    """This migration is not reversible."""
    print("Note: Platform column will remain as VARCHAR with lowercase values (no downgrade action)")
    pass
