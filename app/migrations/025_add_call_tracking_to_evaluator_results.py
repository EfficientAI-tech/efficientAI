"""
Migration 025: Add call_event and provider_call_id to evaluator_results table

This migration adds tracking fields for call status and provider call IDs
to enable detailed status tracking for evaluator results.
"""

from sqlalchemy import text

description = "Add call_event and provider_call_id columns to evaluator_results table"


def upgrade(db):
    """Add call_event and provider_call_id columns to evaluator_results table."""
    # Add call_event column (check if it exists first)
    result = db.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'evaluator_results' 
        AND column_name = 'call_event'
    """))
    if not result.fetchone():
        db.execute(text("""
            ALTER TABLE evaluator_results 
            ADD COLUMN call_event VARCHAR(255)
        """))
    
    # Add index on call_event
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_evaluator_results_call_event 
        ON evaluator_results(call_event)
    """))
    
    # Add provider_call_id column (check if it exists first)
    result = db.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'evaluator_results' 
        AND column_name = 'provider_call_id'
    """))
    if not result.fetchone():
        db.execute(text("""
            ALTER TABLE evaluator_results 
            ADD COLUMN provider_call_id VARCHAR(255)
        """))
    
    # Add index on provider_call_id
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_evaluator_results_provider_call_id 
        ON evaluator_results(provider_call_id)
    """))
    
    db.commit()


def downgrade(db):
    """Remove call_event and provider_call_id columns from evaluator_results table."""
    # Drop indexes first
    db.execute(text("DROP INDEX IF EXISTS ix_evaluator_results_call_event"))
    db.execute(text("DROP INDEX IF EXISTS ix_evaluator_results_provider_call_id"))
    
    # Drop columns
    db.execute(text("ALTER TABLE evaluator_results DROP COLUMN IF EXISTS call_event"))
    db.execute(text("ALTER TABLE evaluator_results DROP COLUMN IF EXISTS provider_call_id"))
    
    db.commit()

