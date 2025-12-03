"""
Migration: Update EvaluatorResult Status Enum
Drops and recreates the evaluator_results table with updated enum values.
This is a clean approach that removes the old 'in_progress' status.
"""

import logging

logger = logging.getLogger(__name__)
description = "Recreate evaluator_results table with updated status enum"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    logger.info("Updating EvaluatorResult status enum by recreating table...")
    
    try:
        # Step 1: Drop the existing table
        logger.info("  Step 1: Dropping existing evaluator_results table...")
        db.execute(text("DROP TABLE IF EXISTS evaluator_results CASCADE"))
        db.commit()
        logger.info("    ✓ Table dropped")
        
        # Step 2: Drop the enum (we'll use VARCHAR instead to avoid serialization issues)
        logger.info("  Step 2: Dropping enum type (will use VARCHAR instead)...")
        db.execute(text("DROP TYPE IF EXISTS evaluatorresultstatus CASCADE"))
        db.commit()
        logger.info("    ✓ Enum dropped")
        
        # Step 3: Recreate the table with VARCHAR for status
        logger.info("  Step 3: Recreating evaluator_results table...")
        db.execute(text("""
            CREATE TABLE evaluator_results (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                result_id VARCHAR(6) UNIQUE NOT NULL,
                organization_id UUID NOT NULL,
                evaluator_id UUID NOT NULL,
                agent_id UUID NOT NULL,
                persona_id UUID NOT NULL,
                scenario_id UUID NOT NULL,
                name VARCHAR NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                duration_seconds FLOAT,
                status VARCHAR(20) NOT NULL DEFAULT 'queued',
                audio_s3_key VARCHAR,
                transcription TEXT,
                metric_scores JSONB,
                celery_task_id VARCHAR,
                error_message VARCHAR,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR,
                CONSTRAINT fk_evaluator_results_organization 
                    FOREIGN KEY (organization_id) REFERENCES organizations(id),
                CONSTRAINT fk_evaluator_results_evaluator 
                    FOREIGN KEY (evaluator_id) REFERENCES evaluators(id),
                CONSTRAINT fk_evaluator_results_agent 
                    FOREIGN KEY (agent_id) REFERENCES agents(id),
                CONSTRAINT fk_evaluator_results_persona 
                    FOREIGN KEY (persona_id) REFERENCES personas(id),
                CONSTRAINT fk_evaluator_results_scenario 
                    FOREIGN KEY (scenario_id) REFERENCES scenarios(id)
            )
        """))
        db.commit()
        logger.info("    ✓ Table recreated")
        
        # Step 4: Recreate indexes
        logger.info("  Step 4: Creating indexes...")
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_result_id ON evaluator_results(result_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_organization_id ON evaluator_results(organization_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_evaluator_id ON evaluator_results(evaluator_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_celery_task_id ON evaluator_results(celery_task_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_status ON evaluator_results(status)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_timestamp ON evaluator_results(timestamp)"))
        db.commit()
        logger.info("    ✓ Indexes created")
        
        logger.info("  ✓ Migration completed successfully")
        
    except Exception as e:
        db.rollback()
        logger.error(f"  ✗ Error recreating table: {e}")
        raise

