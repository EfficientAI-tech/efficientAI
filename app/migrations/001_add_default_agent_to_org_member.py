"""
Migration: Add default_agent_id to organization_members table

This allows users to have a persistent default agent selection per organization.
When the selected agent is deleted, the default_agent_id is set to NULL.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add default_agent_id column to organization_members table"


def upgrade(db: Session):
    """Add default_agent_id column with foreign key to agents table."""
    
    # Check if column already exists
    result = db.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'organization_members' 
        AND column_name = 'default_agent_id'
    """))
    
    if result.fetchone() is not None:
        print("Column default_agent_id already exists, skipping...")
        return
    
    # Add the column
    db.execute(text("""
        ALTER TABLE organization_members 
        ADD COLUMN default_agent_id UUID REFERENCES agents(id) ON DELETE SET NULL
    """))
    
    # Create an index for faster lookups
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_organization_members_default_agent_id 
        ON organization_members(default_agent_id)
    """))
    
    db.commit()
    print("Successfully added default_agent_id column to organization_members")


def downgrade(db: Session):
    """Remove default_agent_id column."""
    db.execute(text("""
        ALTER TABLE organization_members DROP COLUMN IF EXISTS default_agent_id
    """))
    db.commit()
