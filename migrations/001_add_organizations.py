"""
Migration: Add Organizations
Adds organization-based multi-tenancy support.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add organization-based multi-tenancy support"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    import uuid
    
    # 1. Create organizations table
    logger.info("  1. Creating organizations table...")
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS organizations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.commit()
        logger.info("     ✓ Organizations table created")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ Organizations table may already exist: {e}")
        db.rollback()
    
    # 2. Add organization_id column to existing tables
    tables_to_alter = ["api_keys", "audio_files", "evaluations", "batch_jobs", "agents", "personas", "scenarios"]
    for table_name in tables_to_alter:
        logger.info(f"  2. Adding organization_id column to {table_name}...")
        try:
            db.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS organization_id UUID"))
            db.execute(text(f"""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint 
                        WHERE conname = 'fk_{table_name}_organization_id'
                    ) THEN
                        ALTER TABLE {table_name} 
                        ADD CONSTRAINT fk_{table_name}_organization_id 
                        FOREIGN KEY (organization_id) REFERENCES organizations(id);
                    END IF;
                END $$;
            """))
            db.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_organization_id ON {table_name}(organization_id)"))
            db.commit()
            logger.info(f"     ✓ organization_id column added to {table_name}")
        except ProgrammingError as e:
            logger.warning(f"     ⚠ Column organization_id may already exist in {table_name}: {e}")
            db.rollback()
    
    # 3. Create a default organization if none exist
    logger.info("  3. Creating default organization if needed...")
    default_org_name = "Default Organization"
    result = db.execute(text("SELECT id FROM organizations WHERE name = :name"), {"name": default_org_name})
    existing_default_org = result.fetchone()
    
    if not existing_default_org:
        new_org_id = uuid.uuid4()
        db.execute(text("INSERT INTO organizations (id, name) VALUES (:id, :name)"), 
                  {"id": new_org_id, "name": default_org_name})
        db.commit()
        logger.info(f"     ✓ Created default organization '{default_org_name}' with ID: {new_org_id}")
    else:
        logger.info(f"     ✓ Default organization '{default_org_name}' already exists")
    
    # 4. Assign existing records to the default organization
    logger.info("  4. Assigning existing records to the default organization...")
    result = db.execute(text("SELECT id FROM organizations WHERE name = :name"), {"name": default_org_name})
    default_org = result.fetchone()
    if default_org:
        default_org_id = default_org[0]
        for table_name in tables_to_alter:
            try:
                db.execute(text(f"UPDATE {table_name} SET organization_id = :org_id WHERE organization_id IS NULL"), 
                          {"org_id": default_org_id})
                db.commit()
                logger.info(f"     ✓ {table_name} records assigned")
            except Exception as e:
                logger.warning(f"     ⚠ Error assigning {table_name}: {e}")
                db.rollback()
    
    # 5. Make organization_id NOT NULL
    logger.info("  5. Making organization_id NOT NULL...")
    for table_name in tables_to_alter:
        try:
            db.execute(text(f"""
                DO $$ 
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = '{table_name}' 
                        AND column_name = 'organization_id' 
                        AND is_nullable = 'YES'
                    ) THEN
                        ALTER TABLE {table_name} ALTER COLUMN organization_id SET NOT NULL;
                    END IF;
                END $$;
            """))
            db.commit()
            logger.info(f"     ✓ organization_id column in {table_name} set to NOT NULL")
        except ProgrammingError as e:
            logger.warning(f"     ⚠ Column organization_id in {table_name} may already be NOT NULL: {e}")
            db.rollback()
    
    logger.info("  ✓ Migration completed successfully!")

