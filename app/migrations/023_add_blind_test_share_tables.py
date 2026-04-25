"""
Migration: Add tts_blind_test_shares and tts_blind_test_responses tables.

These power the public, sharable blind-test form for any TTSComparison. The
share_token column is the capability that grants public access; raters submit
via /api/v1/public/blind-tests/{token} and rows are aggregated into the
existing comparison's evaluation_summary.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add tts_blind_test_shares and tts_blind_test_responses tables"


def upgrade(db: Session):
    # --- tts_blind_test_shares ---
    result = db.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_name = 'tts_blind_test_shares'
    """))
    if result.fetchone() is None:
        db.execute(text("""
            CREATE TABLE tts_blind_test_shares (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                comparison_id UUID NOT NULL REFERENCES tts_comparisons(id) ON DELETE CASCADE,
                organization_id UUID NOT NULL REFERENCES organizations(id),
                share_token VARCHAR(64) NOT NULL UNIQUE,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                custom_metrics JSONB NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                closed_at TIMESTAMPTZ,
                created_by VARCHAR,
                CONSTRAINT uq_blind_test_shares_comparison UNIQUE (comparison_id)
            )
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_tts_blind_test_shares_comparison_id
            ON tts_blind_test_shares(comparison_id)
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_tts_blind_test_shares_organization_id
            ON tts_blind_test_shares(organization_id)
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_tts_blind_test_shares_share_token
            ON tts_blind_test_shares(share_token)
        """))
        print("Created tts_blind_test_shares table")
    else:
        print("tts_blind_test_shares table already exists, skipping...")

    # --- tts_blind_test_responses ---
    result = db.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_name = 'tts_blind_test_responses'
    """))
    if result.fetchone() is None:
        db.execute(text("""
            CREATE TABLE tts_blind_test_responses (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                share_id UUID NOT NULL REFERENCES tts_blind_test_shares(id) ON DELETE CASCADE,
                rater_name VARCHAR(255) NOT NULL,
                rater_email VARCHAR(320) NOT NULL,
                responses JSONB NOT NULL,
                ip VARCHAR(64),
                user_agent VARCHAR(512),
                submitted_at TIMESTAMPTZ DEFAULT now(),
                CONSTRAINT uq_blind_test_response_share_email UNIQUE (share_id, rater_email)
            )
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_tts_blind_test_responses_share_id
            ON tts_blind_test_responses(share_id)
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_tts_blind_test_responses_rater_email
            ON tts_blind_test_responses(rater_email)
        """))
        print("Created tts_blind_test_responses table")
    else:
        print("tts_blind_test_responses table already exists, skipping...")

    db.commit()
    print("Successfully created blind test share tables")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS tts_blind_test_responses"))
    db.execute(text("DROP TABLE IF EXISTS tts_blind_test_shares"))
    db.commit()
