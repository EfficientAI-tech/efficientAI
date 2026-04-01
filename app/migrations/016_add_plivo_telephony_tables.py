"""
Migration: Add Plivo telephony tables.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add plivo telephony tables for integrations, numbers, verify sessions, and masking sessions"


def _table_exists(db: Session, table_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    )
    return bool(result.scalar())


def upgrade(db: Session):
    """Create Plivo telephony tables and indexes."""

    if not _table_exists(db, "plivo_integrations"):
        db.execute(
            text(
                """
                CREATE TABLE plivo_integrations (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    auth_id VARCHAR(255) NOT NULL,
                    auth_token VARCHAR(512) NOT NULL,
                    verify_app_uuid VARCHAR(255),
                    voice_app_id VARCHAR(255),
                    sip_domain VARCHAR(255),
                    masking_config JSONB,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    last_tested_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    CONSTRAINT uq_plivo_integration_org UNIQUE (organization_id)
                )
                """
            )
        )
        db.execute(
            text("CREATE INDEX ix_plivo_integrations_organization_id ON plivo_integrations(organization_id)")
        )

    if not _table_exists(db, "plivo_phone_numbers"):
        db.execute(
            text(
                """
                CREATE TABLE plivo_phone_numbers (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    plivo_integration_id UUID NOT NULL REFERENCES plivo_integrations(id),
                    phone_number VARCHAR(20) NOT NULL,
                    country_iso2 VARCHAR(2),
                    region VARCHAR(100),
                    number_type VARCHAR(20),
                    capabilities JSONB,
                    plivo_app_id VARCHAR(255),
                    is_masking_pool BOOLEAN NOT NULL DEFAULT FALSE,
                    agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    CONSTRAINT uq_plivo_number_org_phone UNIQUE (organization_id, phone_number)
                )
                """
            )
        )
        db.execute(
            text("CREATE INDEX ix_plivo_phone_numbers_organization_id ON plivo_phone_numbers(organization_id)")
        )
        db.execute(
            text(
                "CREATE INDEX ix_plivo_phone_numbers_plivo_integration_id ON plivo_phone_numbers(plivo_integration_id)"
            )
        )
        db.execute(text("CREATE INDEX ix_plivo_phone_numbers_phone_number ON plivo_phone_numbers(phone_number)"))
        db.execute(text("CREATE INDEX ix_plivo_phone_numbers_agent_id ON plivo_phone_numbers(agent_id)"))

    if not _table_exists(db, "plivo_verify_sessions"):
        db.execute(
            text(
                """
                CREATE TABLE plivo_verify_sessions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    plivo_session_uuid VARCHAR(255) NOT NULL UNIQUE,
                    recipient_number VARCHAR(20) NOT NULL,
                    channel VARCHAR(10) NOT NULL DEFAULT 'voice',
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    initiated_by VARCHAR(255),
                    verify_app_uuid VARCHAR(255),
                    verified_at TIMESTAMP WITH TIME ZONE,
                    expires_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text("CREATE INDEX ix_plivo_verify_sessions_organization_id ON plivo_verify_sessions(organization_id)")
        )
        db.execute(
            text("CREATE INDEX ix_plivo_verify_sessions_plivo_session_uuid ON plivo_verify_sessions(plivo_session_uuid)")
        )

    if not _table_exists(db, "plivo_masked_sessions"):
        db.execute(
            text(
                """
                CREATE TABLE plivo_masked_sessions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    plivo_integration_id UUID NOT NULL REFERENCES plivo_integrations(id),
                    masked_number_id UUID NOT NULL REFERENCES plivo_phone_numbers(id),
                    masked_number VARCHAR(20) NOT NULL,
                    party_a_number VARCHAR(20) NOT NULL,
                    party_b_number VARCHAR(20) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    expires_at TIMESTAMP WITH TIME ZONE,
                    ended_at TIMESTAMP WITH TIME ZONE,
                    metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text("CREATE INDEX ix_plivo_masked_sessions_organization_id ON plivo_masked_sessions(organization_id)")
        )
        db.execute(
            text("CREATE INDEX ix_plivo_masked_sessions_masked_number_id ON plivo_masked_sessions(masked_number_id)")
        )
        db.execute(
            text("CREATE INDEX ix_plivo_masked_sessions_masked_number ON plivo_masked_sessions(masked_number)")
        )
        db.execute(text("CREATE INDEX ix_plivo_masked_sessions_status ON plivo_masked_sessions(status)"))
        db.execute(
            text(
                """
                CREATE UNIQUE INDEX uq_plivo_masked_sessions_masked_number_active
                ON plivo_masked_sessions(masked_number_id)
                WHERE status = 'active'
                """
            )
        )

    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS plivo_masked_sessions"))
    db.execute(text("DROP TABLE IF EXISTS plivo_verify_sessions"))
    db.execute(text("DROP TABLE IF EXISTS plivo_phone_numbers"))
    db.execute(text("DROP TABLE IF EXISTS plivo_integrations"))
    db.commit()
