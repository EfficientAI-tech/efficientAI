"""
Migration 026: Add provider_platform and call_data to evaluator_results table

This migration adds:
- provider_platform: stores which voice AI provider is used (e.g., "retell", "vapi")
- call_data: stores full call details from the provider as JSON
"""

from sqlalchemy import text

description = "Add provider_platform and call_data columns to evaluator_results table"


def upgrade(db):
    """Add provider_platform and call_data columns to evaluator_results table."""
    # Add provider_platform column (check if it exists first)
    result = db.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'evaluator_results' 
        AND column_name = 'provider_platform'
    """))
    if not result.fetchone():
        db.execute(text("""
            ALTER TABLE evaluator_results 
            ADD COLUMN provider_platform VARCHAR(255)
        """))
    
    # Add call_data column (check if it exists first)
    result = db.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'evaluator_results' 
        AND column_name = 'call_data'
    """))
    if not result.fetchone():
        db.execute(text("""
            ALTER TABLE evaluator_results 
            ADD COLUMN call_data JSON
        """))
    
    db.commit()


def downgrade(db):
    """Remove provider_platform and call_data columns from evaluator_results table."""
    db.execute(text("ALTER TABLE evaluator_results DROP COLUMN IF EXISTS provider_platform"))
    db.execute(text("ALTER TABLE evaluator_results DROP COLUMN IF EXISTS call_data"))
    
    db.commit()

