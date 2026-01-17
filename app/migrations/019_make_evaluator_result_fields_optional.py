"""
Migration: Make EvaluatorResult fields optional for test calls without persona/scenario
"""

description = "Make persona_id, scenario_id, evaluator_id, and name nullable in evaluator_results table"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    
    # Make persona_id nullable
    db.execute(text("""
        ALTER TABLE evaluator_results 
        ALTER COLUMN persona_id DROP NOT NULL
    """))
    
    # Make scenario_id nullable
    db.execute(text("""
        ALTER TABLE evaluator_results 
        ALTER COLUMN scenario_id DROP NOT NULL
    """))
    
    # Make evaluator_id nullable
    db.execute(text("""
        ALTER TABLE evaluator_results 
        ALTER COLUMN evaluator_id DROP NOT NULL
    """))
    
    # Make name nullable
    db.execute(text("""
        ALTER TABLE evaluator_results 
        ALTER COLUMN name DROP NOT NULL
    """))
    
    db.commit()

