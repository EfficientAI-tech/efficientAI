"""
Migration: Add Evaluators
Adds evaluators table for managing evaluator configurations with agent, persona, and scenario combinations.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add evaluators table for managing evaluator configurations"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    # 1. Create evaluators table
    logger.info("  1. Creating evaluators table...")
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS evaluators (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                evaluator_id VARCHAR(6) NOT NULL UNIQUE,
                organization_id UUID NOT NULL,
                agent_id UUID NOT NULL,
                persona_id UUID NOT NULL,
                scenario_id UUID NOT NULL,
                tags JSON,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR,
                CONSTRAINT fk_evaluators_organization_id 
                    FOREIGN KEY (organization_id) REFERENCES organizations(id),
                CONSTRAINT fk_evaluators_agent_id 
                    FOREIGN KEY (agent_id) REFERENCES agents(id),
                CONSTRAINT fk_evaluators_persona_id 
                    FOREIGN KEY (persona_id) REFERENCES personas(id),
                CONSTRAINT fk_evaluators_scenario_id 
                    FOREIGN KEY (scenario_id) REFERENCES scenarios(id)
            )
        """))
        db.commit()
        logger.info("  ✓ evaluators table created")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower():
            logger.info("  ✓ evaluators table already exists, skipping")
        else:
            raise
    
    # 2. Create indexes
    logger.info("  2. Creating indexes...")
    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluators_organization_id ON evaluators(organization_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluators_evaluator_id ON evaluators(evaluator_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluators_agent_id ON evaluators(agent_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluators_persona_id ON evaluators(persona_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluators_scenario_id ON evaluators(scenario_id)"))
        db.commit()
        logger.info("  ✓ Indexes created")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower():
            logger.info("  ✓ Indexes already exist, skipping")
        else:
            raise

def downgrade(db):
    """Rollback this migration."""
    from sqlalchemy import text
    
    logger.info("  Dropping evaluators table...")
    db.execute(text("DROP TABLE IF EXISTS evaluators CASCADE"))
    db.commit()
    logger.info("  ✓ evaluators table dropped")

