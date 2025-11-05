"""
Migration: Add IAM Support
Adds user management, organization memberships, and invitations.
"""

import logging

logger = logging.getLogger(__name__)
description = "Add IAM support with users, organization memberships, and invitations"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    from app.models.database import OrganizationMember, RoleEnum, User
    import uuid
    
    # Step 1: Create users table
    logger.info("  1. Creating users table...")
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(255) UNIQUE NOT NULL,
                name VARCHAR(255),
                password_hash VARCHAR(255),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)"))
        db.commit()
        logger.info("     ✓ Users table created with indexes")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ Users table may already exist: {e}")
        db.rollback()
    
    # Step 2: Create roleenum type and organization_members table
    logger.info("  2. Creating roleenum type and organization_members table...")
    try:
        db.execute(text("""
            DO $$ BEGIN
                CREATE TYPE roleenum AS ENUM ('reader', 'writer', 'admin');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS organization_members (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                user_id UUID NOT NULL REFERENCES users(id),
                role roleenum NOT NULL DEFAULT 'reader'::roleenum,
                joined_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(organization_id, user_id)
            )
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_org_members_org_id ON organization_members(organization_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_org_members_user_id ON organization_members(user_id)"))
        db.commit()
        logger.info("     ✓ organization_members table created with indexes and unique constraint")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ organization_members table may already exist: {e}")
        db.rollback()
    
    # Step 3: Create invitationstatus enum and invitations table
    logger.info("  3. Creating invitationstatus enum and invitations table...")
    try:
        db.execute(text("""
            DO $$ BEGIN
                CREATE TYPE invitationstatus AS ENUM ('pending', 'accepted', 'declined', 'expired');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS invitations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                invited_user_id UUID REFERENCES users(id),
                invited_by_id UUID NOT NULL REFERENCES users(id),
                email VARCHAR(255) NOT NULL,
                role roleenum NOT NULL DEFAULT 'reader'::roleenum,
                status invitationstatus NOT NULL DEFAULT 'pending'::invitationstatus,
                token VARCHAR(255) UNIQUE NOT NULL,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                accepted_at TIMESTAMP WITH TIME ZONE
            )
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_invitations_org_id ON invitations(organization_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_invitations_email ON invitations(email)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_invitations_token ON invitations(token)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_invitations_user_id ON invitations(invited_user_id)"))
        db.commit()
        logger.info("     ✓ invitations table created with indexes")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ invitations table may already exist: {e}")
        db.rollback()
    
    # Step 4: Add user_id column to api_keys table
    logger.info("  4. Adding user_id column to api_keys table...")
    try:
        db.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS user_id UUID"))
        db.execute(text("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'fk_api_keys_user_id'
                ) THEN
                    ALTER TABLE api_keys 
                    ADD CONSTRAINT fk_api_keys_user_id 
                    FOREIGN KEY (user_id) REFERENCES users(id);
                END IF;
            END $$;
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id)"))
        db.commit()
        logger.info("     ✓ user_id column added to api_keys")
    except ProgrammingError as e:
        logger.warning(f"     ⚠ Column user_id may already exist in api_keys: {e}")
        db.rollback()
    
    # Step 5: Create default users for existing API keys
    logger.info("  5. Creating default users for existing API keys...")
    try:
        result = db.execute(text("SELECT id, organization_id, name FROM api_keys WHERE user_id IS NULL"))
        api_keys_without_users = result.fetchall()
        
        if api_keys_without_users:
            for api_key_id, org_id, api_key_name in api_keys_without_users:
                email = f"api_user_{api_key_id.hex}@efficientai.local"
                
                # Check if user already exists
                user_check = db.execute(text("SELECT id FROM users WHERE email = :email"), {"email": email})
                existing_user = user_check.fetchone()
                
                if existing_user:
                    user_id = existing_user[0]
                else:
                    # Create new user
                    user_id = uuid.uuid4()
                    db.execute(text("""
                        INSERT INTO users (id, email, name, password_hash, is_active)
                        VALUES (:id, :email, :name, NULL, TRUE)
                    """), {
                        "id": user_id,
                        "email": email,
                        "name": api_key_name
                    })
                    logger.info(f"     ✓ Created user for API key: {email}")
                
                # Link API key to user
                db.execute(text("""
                    UPDATE api_keys
                    SET user_id = :user_id
                    WHERE id = :api_key_id
                """), {
                    "user_id": user_id,
                    "api_key_id": api_key_id
                })
            
            db.commit()
            logger.info(f"     ✓ Linked {len(api_keys_without_users)} API keys to users")
        else:
            logger.info("     ✓ All API keys already have users")
    except Exception as e:
        logger.warning(f"     ⚠ Error creating users for API keys: {e}")
        db.rollback()
    
    # Step 6: Create organization memberships for existing users
    logger.info("  6. Creating organization memberships for API key users...")
    try:
        result = db.execute(text("""
            SELECT DISTINCT ak.organization_id, ak.user_id
            FROM api_keys ak
            WHERE ak.user_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM organization_members om
                WHERE om.organization_id = ak.organization_id
                AND om.user_id = ak.user_id
            )
        """))
        memberships_to_create = result.fetchall()
        
        if memberships_to_create:
            for membership in memberships_to_create:
                org_id = membership[0]
                user_id = membership[1]
                
                # Check if user is the first user in this org (make them admin)
                admin_check = db.execute(text("""
                    SELECT COUNT(*) FROM organization_members
                    WHERE organization_id = :org_id
                """), {"org_id": org_id})
                admin_count = admin_check.fetchone()[0]
                
                role = RoleEnum.ADMIN if admin_count == 0 else RoleEnum.READER
                
                # Check if membership already exists
                existing = db.query(OrganizationMember).filter(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == user_id
                ).first()
                
                if not existing:
                    member = OrganizationMember(
                        organization_id=org_id,
                        user_id=user_id,
                        role=role
                    )
                    db.add(member)
            
            db.commit()
            logger.info(f"     ✓ Created {len(memberships_to_create)} organization memberships")
            logger.info("     ✓ First user in each organization assigned ADMIN role")
        else:
            logger.info("     ✓ All users already have organization memberships")
    except Exception as e:
        logger.warning(f"     ⚠ Error creating memberships: {e}")
        db.rollback()
    
    logger.info("  ✓ Migration completed successfully!")

