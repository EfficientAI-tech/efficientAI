"""Migration: Add metric categories and report snapshot storage."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add metric_category to metrics and report snapshot table."


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
    if not _column_exists(db, "metrics", "metric_category"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN metric_category VARCHAR(30) NOT NULL DEFAULT 'quality'
                """
            )
        )
        print("Added metrics.metric_category")
    else:
        print("metrics.metric_category already exists, skipping")

    db.execute(
        text(
            """
            UPDATE metrics
            SET metric_category = 'user_insight'
            WHERE lower(coalesce(name, '') || ' ' || coalesce(description, '')) LIKE ANY (
                ARRAY[
                    '%call context%',
                    '%caller context%',
                    '%product identification%',
                    '%out of scope%',
                    '%identity match%',
                    '%user identity%',
                    '%caller identity%',
                    '%frustration trigger%',
                    '%video call offer%',
                    '%video-call reception%'
                ]
            )
            """
        )
    )

    if not _table_exists(db, "call_import_evaluation_report_snapshots"):
        db.execute(
            text(
                """
                CREATE TABLE call_import_evaluation_report_snapshots (
                    id UUID PRIMARY KEY,
                    evaluation_id UUID NOT NULL REFERENCES call_import_evaluations(id) ON DELETE CASCADE,
                    call_import_id UUID NOT NULL REFERENCES call_imports(id) ON DELETE CASCADE,
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    workspace_id UUID NOT NULL REFERENCES workspaces(id),
                    period_label VARCHAR(64),
                    period_start DATE,
                    period_end DATE,
                    report_config JSONB NOT NULL DEFAULT '{}'::jsonb,
                    selected_metric_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    metric_aggregates JSONB NOT NULL DEFAULT '[]'::jsonb,
                    insight_aggregates JSONB NOT NULL DEFAULT '[]'::jsonb,
                    narrative JSONB,
                    total_calls INTEGER NOT NULL DEFAULT 0,
                    selected_metric_count INTEGER NOT NULL DEFAULT 0,
                    total_metric_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_call_import_eval_report_snapshots_lookup
                ON call_import_evaluation_report_snapshots
                (workspace_id, period_start, created_at)
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_call_import_eval_report_snapshots_eval
                ON call_import_evaluation_report_snapshots (evaluation_id)
                """
            )
        )
        print("Created call_import_evaluation_report_snapshots")
    else:
        print("call_import_evaluation_report_snapshots already exists, skipping")

    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS call_import_evaluation_report_snapshots"))
    db.execute(text("ALTER TABLE metrics DROP COLUMN IF EXISTS metric_category"))
    db.commit()
