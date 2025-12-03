"""
Migration: Add Metrics
Adds metrics table for managing evaluation metrics configuration.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add metrics table for managing evaluation metrics"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    # 1. Create metrictype enum
    logger.info("  1. Creating metrictype enum...")
    try:
        db.execute(text("""
            DO $$ BEGIN
                CREATE TYPE metrictype AS ENUM ('number', 'boolean', 'rating');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        db.commit()
        logger.info("  ✓ metrictype enum created")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower():
            logger.info("  ✓ metrictype enum already exists, skipping")
        else:
            raise
    
    # 2. Create metrictrigger enum
    logger.info("  2. Creating metrictrigger enum...")
    try:
        db.execute(text("""
            DO $$ BEGIN
                CREATE TYPE metrictrigger AS ENUM ('always');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        db.commit()
        logger.info("  ✓ metrictrigger enum created")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower():
            logger.info("  ✓ metrictrigger enum already exists, skipping")
        else:
            raise
    
    # 3. Create metrics table
    logger.info("  3. Creating metrics table...")
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS metrics (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL,
                name VARCHAR NOT NULL,
                description VARCHAR,
                metric_type metrictype NOT NULL DEFAULT 'rating',
                trigger metrictrigger NOT NULL DEFAULT 'always',
                enabled BOOLEAN NOT NULL DEFAULT true,
                is_default BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR,
                CONSTRAINT fk_metrics_organization_id 
                    FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
        """))
        db.commit()
        logger.info("  ✓ metrics table created")
    except ProgrammingError as e:
        db.rollback()
        if "already exists" in str(e).lower():
            logger.info("  ✓ metrics table already exists, skipping")
        else:
            raise
    
    # 4. Create indexes
    logger.info("  4. Creating indexes...")
    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_metrics_organization_id ON metrics(organization_id)"))
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
    
    logger.info("  Dropping metrics table...")
    db.execute(text("DROP TABLE IF EXISTS metrics CASCADE"))
    db.commit()
    logger.info("  ✓ metrics table dropped")
    
    logger.info("  Dropping enums...")
    db.execute(text("DROP TYPE IF EXISTS metrictrigger CASCADE"))
    db.execute(text("DROP TYPE IF EXISTS metrictype CASCADE"))
    db.commit()
    logger.info("  ✓ Enums dropped")

