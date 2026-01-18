"""
Migration 027: Add public_key column to integrations table

This migration adds a public_key field to store optional public API keys
for integrations like Vapi that require both private and public keys.
"""

from sqlalchemy import text

description = "Add public_key column to integrations table for Vapi and similar integrations"


def upgrade(db):
    """Add public_key column to integrations table."""
    # Check if column already exists
    result = db.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'integrations' 
        AND column_name = 'public_key'
    """))
    
    if not result.fetchone():
        db.execute(text("""
            ALTER TABLE integrations 
            ADD COLUMN public_key VARCHAR(255)
        """))
        print("Added public_key column to integrations table")
    else:
        print("public_key column already exists in integrations table")
    
    db.commit()


def downgrade(db):
    """Remove public_key column from integrations table."""
    db.execute(text("ALTER TABLE integrations DROP COLUMN IF EXISTS public_key"))
    db.commit()
