"""
Migration: Add Judge Alignment tables (AlignEval-style hybrid integration).

Creates:
    - judge_datasets       - container for binary-labeled samples
    - judge_samples        - input/output pair with optional pass/fail label
    - judge_runs           - one execution of an LLM-judge over a dataset
                             with computed alignment metrics

Also backfills:
    - organizations.judge_alignment_settings (JSON, nullable)
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add judge_datasets / judge_samples / judge_runs and judge_alignment_settings on organizations"


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


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = :column_name
            )
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


def upgrade(db: Session):
    # 1. Add judge_alignment_settings on organizations.
    if _table_exists(db, "organizations") and not _column_exists(
        db, "organizations", "judge_alignment_settings"
    ):
        db.execute(
            text(
                """
                ALTER TABLE organizations
                ADD COLUMN judge_alignment_settings JSON
                """
            )
        )

    # 2. judge_datasets
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS judge_datasets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id),

            name VARCHAR(255) NOT NULL,
            description TEXT,

            source_type VARCHAR(32) NOT NULL,
            source_config JSON NOT NULL DEFAULT '{}'::json,

            input_field VARCHAR(64) NOT NULL DEFAULT 'input',
            output_field VARCHAR(64) NOT NULL DEFAULT 'output',

            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            created_by VARCHAR
        )
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_judge_datasets_org
            ON judge_datasets (organization_id)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_judge_datasets_source_type
            ON judge_datasets (source_type)
    """))

    # 3. judge_samples
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS judge_samples (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_id UUID NOT NULL
                REFERENCES judge_datasets(id) ON DELETE CASCADE,

            external_id VARCHAR(128),

            input_text TEXT NOT NULL,
            output_text TEXT NOT NULL,

            label VARCHAR(16),
            labeled_by VARCHAR(255),
            labeled_at TIMESTAMPTZ,

            extra JSON,

            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),

            CONSTRAINT uq_judge_samples_dataset_external
                UNIQUE (dataset_id, external_id)
        )
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_judge_samples_dataset
            ON judge_samples (dataset_id)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_judge_samples_external_id
            ON judge_samples (external_id)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_judge_samples_label
            ON judge_samples (label)
    """))

    # 4. judge_runs
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS judge_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_id UUID NOT NULL
                REFERENCES judge_datasets(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id),

            evaluator_id UUID
                REFERENCES evaluators(id) ON DELETE SET NULL,

            split VARCHAR(16) NOT NULL DEFAULT 'all',

            llm_provider VARCHAR(64),
            llm_model VARCHAR(128),

            metrics JSON,
            predictions JSON,

            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            error_message TEXT,
            celery_task_id VARCHAR,

            gepa_optimization_id UUID
                REFERENCES prompt_optimization_runs(id) ON DELETE SET NULL,

            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            created_by VARCHAR
        )
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_judge_runs_dataset
            ON judge_runs (dataset_id)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_judge_runs_org
            ON judge_runs (organization_id)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_judge_runs_evaluator
            ON judge_runs (evaluator_id)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_judge_runs_status
            ON judge_runs (status)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_judge_runs_celery
            ON judge_runs (celery_task_id)
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_judge_runs_gepa
            ON judge_runs (gepa_optimization_id)
    """))

    db.commit()
    print("Created judge_datasets, judge_samples, judge_runs tables")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS judge_runs CASCADE"))
    db.execute(text("DROP TABLE IF EXISTS judge_samples CASCADE"))
    db.execute(text("DROP TABLE IF EXISTS judge_datasets CASCADE"))

    if _table_exists(db, "organizations") and _column_exists(
        db, "organizations", "judge_alignment_settings"
    ):
        db.execute(text("ALTER TABLE organizations DROP COLUMN judge_alignment_settings"))

    db.commit()
    print("Dropped judge alignment tables")
