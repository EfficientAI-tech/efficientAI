"""
Migration: Add tts_comparisons and tts_samples tables for Voice Playground TTS A/B testing.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add tts_comparisons and tts_samples tables for TTS A/B testing"


def upgrade(db: Session):
    """Create tts_comparisons and tts_samples tables."""

    # --- tts_comparisons ---
    result = db.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_name = 'tts_comparisons'
    """))
    if result.fetchone() is None:
        db.execute(text("""
            CREATE TABLE tts_comparisons (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                name VARCHAR(255),
                status VARCHAR(50) NOT NULL DEFAULT 'pending',
                provider_a VARCHAR(100) NOT NULL,
                model_a VARCHAR(100) NOT NULL,
                voices_a JSONB NOT NULL,
                provider_b VARCHAR(100) NOT NULL,
                model_b VARCHAR(100) NOT NULL,
                voices_b JSONB NOT NULL,
                sample_texts JSONB NOT NULL,
                blind_test_results JSONB,
                evaluation_summary JSONB,
                celery_task_id VARCHAR,
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                created_by VARCHAR
            )
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_tts_comparisons_organization_id
            ON tts_comparisons(organization_id)
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_tts_comparisons_celery_task_id
            ON tts_comparisons(celery_task_id)
        """))
        print("Created tts_comparisons table")
    else:
        print("tts_comparisons table already exists, skipping...")

    # --- tts_samples ---
    result = db.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_name = 'tts_samples'
    """))
    if result.fetchone() is None:
        db.execute(text("""
            CREATE TABLE tts_samples (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                comparison_id UUID NOT NULL REFERENCES tts_comparisons(id) ON DELETE CASCADE,
                organization_id UUID NOT NULL REFERENCES organizations(id),
                provider VARCHAR(100) NOT NULL,
                model VARCHAR(100) NOT NULL,
                voice_id VARCHAR(255) NOT NULL,
                voice_name VARCHAR(255),
                sample_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                audio_s3_key VARCHAR(512),
                duration_seconds DOUBLE PRECISION,
                latency_ms DOUBLE PRECISION,
                evaluation_metrics JSONB,
                status VARCHAR(50) NOT NULL DEFAULT 'pending',
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_tts_samples_comparison_id
            ON tts_samples(comparison_id)
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_tts_samples_organization_id
            ON tts_samples(organization_id)
        """))
        print("Created tts_samples table")
    else:
        print("tts_samples table already exists, skipping...")

    db.commit()
    print("Successfully created TTS comparison tables")


def downgrade(db: Session):
    """Drop tts_samples and tts_comparisons tables."""
    db.execute(text("DROP TABLE IF EXISTS tts_samples"))
    db.execute(text("DROP TABLE IF EXISTS tts_comparisons"))
    db.commit()
