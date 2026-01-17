"""
Migration 030: Normalize provider values to lowercase in aiproviders table

This migration converts the provider column from enum type to VARCHAR
and normalizes values to lowercase to match the ModelProvider enum values.
"""

from sqlalchemy import text

description = "Convert provider column to VARCHAR and normalize to lowercase in aiproviders table"


def upgrade(db):
    """Convert provider column to VARCHAR and normalize to lowercase."""
    
    # Check column data type
    result = db.execute(text("""
        SELECT data_type, udt_name 
        FROM information_schema.columns 
        WHERE table_name = 'aiproviders' 
        AND column_name = 'provider'
    """))
    row = result.fetchone()
    
    if row:
        data_type, udt_name = row
        
        # If it's an enum (USER-DEFINED), convert to VARCHAR
        if data_type == 'USER-DEFINED' or udt_name == 'modelprovider':
            print(f"Converting aiproviders.provider from enum to VARCHAR...")
            db.execute(text("""
                ALTER TABLE aiproviders 
                ALTER COLUMN provider TYPE VARCHAR(50) 
                USING provider::text
            """))
        
        # Now normalize to lowercase (it's now VARCHAR)
        db.execute(text("""
            UPDATE aiproviders 
            SET provider = LOWER(provider::text) 
            WHERE provider IS NOT NULL
        """))
    
    print("Normalized provider values in aiproviders table")
    db.commit()


def downgrade(db):
    """This migration is not reversible - values remain lowercase and as VARCHAR."""
    print("Note: Provider column will remain as VARCHAR with lowercase values (no downgrade action)")
    pass
