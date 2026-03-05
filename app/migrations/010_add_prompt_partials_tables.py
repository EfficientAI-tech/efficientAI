"""
Migration: Add prompt_partials and prompt_partial_versions tables
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add prompt_partials and prompt_partial_versions tables for reusable prompt templates with version history"


def upgrade(db: Session):
    """Create prompt_partials and prompt_partial_versions tables."""

    # Check if prompt_partials table already exists
    result = db.execute(
        text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'prompt_partials')")
    )
    if result.scalar():
        return

    db.execute(text("""
        CREATE TABLE prompt_partials (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id),
            name VARCHAR(255) NOT NULL,
            description TEXT,
            content TEXT NOT NULL,
            tags JSONB,
            current_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            created_by VARCHAR
        )
    """))

    db.execute(text("CREATE INDEX ix_prompt_partials_organization_id ON prompt_partials(organization_id)"))

    db.execute(text("""
        CREATE TABLE prompt_partial_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            prompt_partial_id UUID NOT NULL REFERENCES prompt_partials(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            change_summary VARCHAR,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            created_by VARCHAR,
            CONSTRAINT uq_prompt_partial_version UNIQUE (prompt_partial_id, version)
        )
    """))

    db.execute(text("CREATE INDEX ix_prompt_partial_versions_prompt_partial_id ON prompt_partial_versions(prompt_partial_id)"))

    db.commit()
