"""
Migration: Configurable Call Imports + Evaluation tables.

Adds:
  * ``call_imports.telephony_integration_id`` - pin a specific telephony
    credential row for the upload (NULL = legacy default-by-provider).
  * ``call_imports.column_mapping`` - JSON describing how CSV headers map
    to system fields (``external_call_id``, ``transcript``, ``recording_url``).
  * ``call_imports.extra_columns`` - JSON list of additional CSV headers
    to preserve verbatim for export.
  * ``call_import_rows.raw_columns`` - JSON snapshot of the original CSV
    row keyed by header so the export step can rebuild the user's columns.
  * ``call_import_evaluations`` - parent record for an evaluation run over
    a CallImport batch with a chosen subset of metrics.
  * ``call_import_evaluation_rows`` - per-CallImportRow scoring output for
    a CallImportEvaluation parent.

Idempotent: every step checks for prior existence before applying.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add column mapping + telephony credential pin to call imports and "
    "create call_import_evaluations / call_import_evaluation_rows tables"
)


def _column_exists(db: Session, table: str, column: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table, "column_name": column},
    ).first()
    return row is not None


def _table_exists(db: Session, table: str) -> bool:
    row = db.execute(
        text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
        ),
        {"t": table},
    ).first()
    return row is not None


def _index_exists(db: Session, name: str) -> bool:
    row = db.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :n"),
        {"n": name},
    ).first()
    return row is not None


def upgrade(db: Session):
    # --- call_imports additions ---
    if _table_exists(db, "call_imports"):
        if not _column_exists(db, "call_imports", "telephony_integration_id"):
            db.execute(
                text(
                    """
                    ALTER TABLE call_imports
                    ADD COLUMN telephony_integration_id UUID NULL
                        REFERENCES telephony_integrations(id) ON DELETE SET NULL
                    """
                )
            )
            print("Added call_imports.telephony_integration_id")
        if not _column_exists(db, "call_imports", "column_mapping"):
            db.execute(
                text(
                    """
                    ALTER TABLE call_imports
                    ADD COLUMN column_mapping JSONB NOT NULL DEFAULT '{}'::jsonb
                    """
                )
            )
            print("Added call_imports.column_mapping")
        if not _column_exists(db, "call_imports", "extra_columns"):
            db.execute(
                text(
                    """
                    ALTER TABLE call_imports
                    ADD COLUMN extra_columns JSONB NOT NULL DEFAULT '[]'::jsonb
                    """
                )
            )
            print("Added call_imports.extra_columns")

    # --- call_import_rows additions ---
    if _table_exists(db, "call_import_rows") and not _column_exists(
        db, "call_import_rows", "raw_columns"
    ):
        db.execute(
            text(
                "ALTER TABLE call_import_rows ADD COLUMN raw_columns JSONB NULL"
            )
        )
        print("Added call_import_rows.raw_columns")

    # --- call_import_evaluations table ---
    if not _table_exists(db, "call_import_evaluations"):
        db.execute(
            text(
                """
                CREATE TABLE call_import_evaluations (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    call_import_id UUID NOT NULL
                        REFERENCES call_imports(id) ON DELETE CASCADE,
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    created_by_user_id UUID REFERENCES users(id),
                    selected_metric_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    total_rows INTEGER NOT NULL DEFAULT 0,
                    completed_rows INTEGER NOT NULL DEFAULT 0,
                    failed_rows INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    celery_group_id VARCHAR(255),
                    started_at TIMESTAMP WITH TIME ZONE,
                    finished_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_call_import_evaluations_call_import_id "
                "ON call_import_evaluations(call_import_id)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_call_import_evaluations_organization_id "
                "ON call_import_evaluations(organization_id)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_call_import_evaluations_status "
                "ON call_import_evaluations(status)"
            )
        )
        print("Created call_import_evaluations table")

    # --- call_import_evaluation_rows table ---
    if not _table_exists(db, "call_import_evaluation_rows"):
        db.execute(
            text(
                """
                CREATE TABLE call_import_evaluation_rows (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    evaluation_id UUID NOT NULL
                        REFERENCES call_import_evaluations(id) ON DELETE CASCADE,
                    call_import_row_id UUID NOT NULL
                        REFERENCES call_import_rows(id) ON DELETE CASCADE,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    metric_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
                    error_message TEXT,
                    celery_task_id VARCHAR(255),
                    started_at TIMESTAMP WITH TIME ZONE,
                    finished_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    CONSTRAINT uq_call_import_evaluation_row UNIQUE
                        (evaluation_id, call_import_row_id)
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_call_import_evaluation_rows_evaluation_id "
                "ON call_import_evaluation_rows(evaluation_id)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_call_import_evaluation_rows_row_id "
                "ON call_import_evaluation_rows(call_import_row_id)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_call_import_evaluation_rows_status "
                "ON call_import_evaluation_rows(status)"
            )
        )
        print("Created call_import_evaluation_rows table")

    db.commit()
    print("Call import mapping + evaluation schema is in place")


def downgrade(db: Session):
    for idx in (
        "ix_call_import_evaluation_rows_status",
        "ix_call_import_evaluation_rows_row_id",
        "ix_call_import_evaluation_rows_evaluation_id",
        "ix_call_import_evaluations_status",
        "ix_call_import_evaluations_organization_id",
        "ix_call_import_evaluations_call_import_id",
    ):
        db.execute(text(f"DROP INDEX IF EXISTS {idx}"))
    db.execute(text("DROP TABLE IF EXISTS call_import_evaluation_rows"))
    db.execute(text("DROP TABLE IF EXISTS call_import_evaluations"))
    db.execute(text("ALTER TABLE call_import_rows DROP COLUMN IF EXISTS raw_columns"))
    db.execute(text("ALTER TABLE call_imports DROP COLUMN IF EXISTS extra_columns"))
    db.execute(text("ALTER TABLE call_imports DROP COLUMN IF EXISTS column_mapping"))
    db.execute(
        text(
            "ALTER TABLE call_imports DROP COLUMN IF EXISTS telephony_integration_id"
        )
    )
    db.commit()
