"""
Migration: Add evaluator_result_id to call_recordings table

This allows linking Voice AI agent call recordings to their evaluation results
after metrics evaluation has been run.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add evaluator_result_id column to call_recordings table"


def upgrade(db: Session):
    """Add evaluator_result_id column with foreign key to evaluator_results table."""
    
    # Check if column already exists
    result = db.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'call_recordings' 
        AND column_name = 'evaluator_result_id'
    """))
    
    if result.fetchone() is not None:
        print("Column evaluator_result_id already exists, skipping...")
        return
    
    # Add the column
    db.execute(text("""
        ALTER TABLE call_recordings 
        ADD COLUMN evaluator_result_id UUID REFERENCES evaluator_results(id) ON DELETE SET NULL
    """))
    
    # Create an index for faster lookups
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_call_recordings_evaluator_result_id 
        ON call_recordings(evaluator_result_id)
    """))
    
    db.commit()
    print("Successfully added evaluator_result_id column to call_recordings")


def downgrade(db: Session):
    """Remove evaluator_result_id column."""
    db.execute(text("""
        ALTER TABLE call_recordings DROP COLUMN IF EXISTS evaluator_result_id
    """))
    db.commit()
