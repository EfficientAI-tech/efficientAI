"""
Migration: platform admin tables, org disable flag, signup reference codes.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add platform admin auth, org is_active flag, and signup reference codes."


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _column_exists(db, "organizations", "is_active"):
        db.execute(
            text(
                """
                ALTER TABLE organizations
                ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_organizations_is_active
                ON organizations (is_active)
                """
            )
        )
        print("Added organizations.is_active")

    if not _column_exists(db, "organizations", "disabled_at"):
        db.execute(
            text(
                """
                ALTER TABLE organizations
                ADD COLUMN disabled_at TIMESTAMP WITH TIME ZONE NULL
                """
            )
        )
        print("Added organizations.disabled_at")

    if not _table_exists(db, "platform_admins"):
        db.execute(
            text(
                """
                CREATE TABLE platform_admins (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email VARCHAR(255) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    last_login_at TIMESTAMP WITH TIME ZONE NULL
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_platform_admins_email
                ON platform_admins (email)
                """
            )
        )
        print("Added platform_admins table")

    if not _table_exists(db, "signup_reference_codes"):
        db.execute(
            text(
                """
                CREATE TABLE signup_reference_codes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    code_hash VARCHAR(64) NOT NULL UNIQUE,
                    label VARCHAR(255) NULL,
                    max_uses INTEGER NULL,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    expires_at TIMESTAMP WITH TIME ZONE NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_by UUID NULL REFERENCES platform_admins(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_signup_reference_codes_is_active
                ON signup_reference_codes (is_active)
                """
            )
        )
        print("Added signup_reference_codes table")

    db.commit()


def downgrade(db: Session):
    if _table_exists(db, "signup_reference_codes"):
        db.execute(text("DROP TABLE signup_reference_codes"))
        print("Dropped signup_reference_codes table")

    if _table_exists(db, "platform_admins"):
        db.execute(text("DROP TABLE platform_admins"))
        print("Dropped platform_admins table")

    if _column_exists(db, "organizations", "disabled_at"):
        db.execute(text("ALTER TABLE organizations DROP COLUMN disabled_at"))
        print("Dropped organizations.disabled_at")

    if _column_exists(db, "organizations", "is_active"):
        db.execute(text("DROP INDEX IF EXISTS ix_organizations_is_active"))
        db.execute(text("ALTER TABLE organizations DROP COLUMN is_active"))
        print("Dropped organizations.is_active")

    db.commit()
