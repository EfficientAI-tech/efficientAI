"""
Migration: Add Evaluator Results
Creates table for storing evaluator run results with transcription and metric evaluations.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add evaluator_results table for storing evaluation results"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    # 1. Create EvaluatorResultStatus enum
    logger.info("  1. Creating EvaluatorResultStatus enum...")
    try:
        db.execute(text("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'evaluatorresultstatus') THEN
                    CREATE TYPE evaluatorresultstatus AS ENUM ('in_progress', 'completed', 'failed');
                END IF;
            END $$;
        """))
        db.commit()
        logger.info("  ✓ EvaluatorResultStatus enum created")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower():
            logger.info("  ✓ EvaluatorResultStatus enum already exists, skipping")
        else:
            raise
    
    # 2. Create evaluator_results table
    logger.info("  2. Creating evaluator_results table...")
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS evaluator_results (
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
                status evaluatorresultstatus NOT NULL DEFAULT 'in_progress',
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
        logger.info("  ✓ evaluator_results table created")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower():
            logger.info("  ✓ evaluator_results table already exists, skipping")
        else:
            raise
    
    # 3. Create indexes
    logger.info("  3. Creating indexes...")
    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_result_id ON evaluator_results(result_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_organization_id ON evaluator_results(organization_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_evaluator_id ON evaluator_results(evaluator_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_celery_task_id ON evaluator_results(celery_task_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_status ON evaluator_results(status)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_evaluator_results_timestamp ON evaluator_results(timestamp)"))
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
    
    logger.info("  Removing evaluator_results table...")
    db.execute(text("DROP TABLE IF EXISTS evaluator_results CASCADE"))
    db.execute(text("DROP TYPE IF EXISTS evaluatorresultstatus CASCADE"))
    db.commit()
    logger.info("  ✓ Table and enum removed")

