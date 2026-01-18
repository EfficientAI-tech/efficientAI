"""
Migration 032: Add cron_jobs table

This migration creates the table needed for scheduling automated evaluator runs:
- cron_jobs: Stores cron job configurations
"""

from sqlalchemy import text

description = "Add cron_jobs table for scheduling automated evaluator runs"


def upgrade(db):
    """Run the migration."""
    # Check if cron_jobs table already exists
    result = db.execute(text("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_name = 'cron_jobs'
    """))
    
    if not result.fetchone():
        # Create cron_jobs table
        db.execute(text("""
            CREATE TABLE cron_jobs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                
                -- Basic information
                name VARCHAR(255) NOT NULL,
                cron_expression VARCHAR(100) NOT NULL,
                timezone VARCHAR(100) NOT NULL DEFAULT 'UTC',
                
                -- Run configuration
                max_runs INTEGER NOT NULL DEFAULT 10,
                current_runs INTEGER NOT NULL DEFAULT 0,
                
                -- Evaluators to trigger (JSON array of evaluator UUIDs)
                evaluator_ids JSONB NOT NULL,
                
                -- Status
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                
                -- Run tracking
                next_run_at TIMESTAMP WITH TIME ZONE,
                last_run_at TIMESTAMP WITH TIME ZONE,
                
                -- Metadata
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                created_by VARCHAR(255)
            )
        """))
        
        # Create indexes
        db.execute(text("""
            CREATE INDEX idx_cron_jobs_organization_id ON cron_jobs(organization_id)
        """))
        db.execute(text("""
            CREATE INDEX idx_cron_jobs_status ON cron_jobs(status)
        """))
        db.execute(text("""
            CREATE INDEX idx_cron_jobs_next_run_at ON cron_jobs(next_run_at)
        """))
        
        print("Created cron_jobs table with indexes")
    else:
        print("cron_jobs table already exists")
    
    db.commit()


def downgrade(db):
    """Rollback the migration."""
    db.execute(text("DROP TABLE IF EXISTS cron_jobs CASCADE"))
    db.commit()
    print("Dropped cron_jobs table")
