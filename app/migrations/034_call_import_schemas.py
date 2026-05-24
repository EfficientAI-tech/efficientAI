"""
Migration: Reusable Input Parameter schemas for Call Uploads.

Introduces a per-workspace schema definition that drives the new
parameter-first upload flow:

  * ``call_import_schemas`` - one row per (workspace, named schema).
  * ``call_import_schema_parameters`` - typed parameter rows attached to
    a schema (each schema MUST contain a single ``conversation_id``-typed
    required parameter; enforced in app code).

Also reshapes ``call_imports`` / ``call_import_rows`` to match the new
upload contract:

  * Renames ``call_import_rows.external_call_id`` -> ``conversation_id``
    (single ``ALTER COLUMN ... RENAME``, index renamed in lockstep).
    Legacy data flows through unchanged - just under a new column name.
  * Adds ``call_imports.schema_id`` (nullable FK; legacy imports keep
    ``NULL`` and continue to be readable via the existing free-form
    ``column_mapping`` / ``extra_columns`` / ``custom_column_mapping``
    JSONB columns).
  * Adds ``call_imports.parameter_mapping`` JSONB storing
    ``{schema_parameter_name: csv_header}`` for new uploads.

Idempotent: every step checks for prior existence before applying so a
partially-applied run can resume cleanly.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add call_import_schemas + call_import_schema_parameters tables, "
    "rename call_import_rows.external_call_id to conversation_id, and "
    "add call_imports.schema_id + call_imports.parameter_mapping."
)


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


def _index_exists(db: Session, index_name: str) -> bool:
    row = db.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :index_name"),
        {"index_name": index_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    # 1. call_import_schemas table.
    if not _table_exists(db, "call_import_schemas"):
        db.execute(
            text(
                """
                CREATE TABLE call_import_schemas (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL
                        REFERENCES organizations(id) ON DELETE CASCADE,
                    workspace_id UUID NOT NULL
                        REFERENCES workspaces(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    created_by_user_id UUID NULL
                        REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )
        )
        print("Created call_import_schemas table")
    else:
        print("call_import_schemas table already exists, skipping...")

    db.execute(
        text(
            "ALTER TABLE call_import_schemas "
            "ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        )
    )

    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_call_import_schemas_workspace "
            "ON call_import_schemas(workspace_id)"
        )
    )
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_call_import_schemas_organization "
            "ON call_import_schemas(organization_id)"
        )
    )
    # Case-insensitive uniqueness on (workspace_id, name) so the UI can
    # safely treat "Default" and "default" as the same schema.
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_call_import_schemas_ws_name
            ON call_import_schemas(workspace_id, LOWER(name))
            """
        )
    )

    # 2. call_import_schema_parameters table.
    if not _table_exists(db, "call_import_schema_parameters"):
        db.execute(
            text(
                """
                CREATE TABLE call_import_schema_parameters (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    schema_id UUID NOT NULL
                        REFERENCES call_import_schemas(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(32) NOT NULL,
                    description TEXT,
                    is_required BOOLEAN NOT NULL DEFAULT FALSE,
                    ordering INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )
        )
        print("Created call_import_schema_parameters table")
    else:
        print("call_import_schema_parameters table already exists, skipping...")

    db.execute(
        text(
            "ALTER TABLE call_import_schema_parameters "
            "ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        )
    )

    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_call_import_schema_params_schema "
            "ON call_import_schema_parameters(schema_id)"
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_call_import_schema_params_name
            ON call_import_schema_parameters(schema_id, LOWER(name))
            """
        )
    )

    # 3. Rename call_import_rows.external_call_id -> conversation_id.
    # The DB column rename is cheap (metadata-only) and keeps existing
    # data intact - readers/writers just see the new name from now on.
    if _table_exists(db, "call_import_rows"):
        if _column_exists(db, "call_import_rows", "external_call_id") and not _column_exists(
            db, "call_import_rows", "conversation_id"
        ):
            db.execute(
                text(
                    "ALTER TABLE call_import_rows "
                    "RENAME COLUMN external_call_id TO conversation_id"
                )
            )
            print("Renamed call_import_rows.external_call_id -> conversation_id")
        else:
            print(
                "call_import_rows.conversation_id already in place "
                "(or external_call_id missing), skipping rename..."
            )

        if _index_exists(db, "ix_call_import_rows_external_call_id"):
            db.execute(
                text(
                    "ALTER INDEX ix_call_import_rows_external_call_id "
                    "RENAME TO ix_call_import_rows_conversation_id"
                )
            )
            print(
                "Renamed index ix_call_import_rows_external_call_id "
                "-> ix_call_import_rows_conversation_id"
            )

    # 4. call_imports.schema_id (nullable FK).
    if _table_exists(db, "call_imports"):
        if not _column_exists(db, "call_imports", "schema_id"):
            db.execute(
                text(
                    """
                    ALTER TABLE call_imports
                    ADD COLUMN schema_id UUID NULL
                        REFERENCES call_import_schemas(id) ON DELETE RESTRICT
                    """
                )
            )
            print("Added call_imports.schema_id")
        else:
            print("call_imports.schema_id already exists, skipping...")

        db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_call_imports_schema_id "
                "ON call_imports(schema_id)"
            )
        )

        # 5. call_imports.parameter_mapping JSONB.
        if not _column_exists(db, "call_imports", "parameter_mapping"):
            db.execute(
                text(
                    """
                    ALTER TABLE call_imports
                    ADD COLUMN parameter_mapping JSONB NOT NULL DEFAULT '{}'::jsonb
                    """
                )
            )
            print("Added call_imports.parameter_mapping")
        else:
            print("call_imports.parameter_mapping already exists, skipping...")

    db.commit()
    print("call_import_schemas migration complete")


def downgrade(db: Session):
    if _column_exists(db, "call_imports", "parameter_mapping"):
        db.execute(
            text("ALTER TABLE call_imports DROP COLUMN parameter_mapping")
        )
    if _column_exists(db, "call_imports", "schema_id"):
        db.execute(text("ALTER TABLE call_imports DROP COLUMN schema_id"))
    db.execute(text("DROP INDEX IF EXISTS ix_call_imports_schema_id"))

    if _index_exists(db, "ix_call_import_rows_conversation_id"):
        db.execute(
            text(
                "ALTER INDEX ix_call_import_rows_conversation_id "
                "RENAME TO ix_call_import_rows_external_call_id"
            )
        )
    if _column_exists(db, "call_import_rows", "conversation_id") and not _column_exists(
        db, "call_import_rows", "external_call_id"
    ):
        db.execute(
            text(
                "ALTER TABLE call_import_rows "
                "RENAME COLUMN conversation_id TO external_call_id"
            )
        )

    db.execute(text("DROP TABLE IF EXISTS call_import_schema_parameters"))
    db.execute(text("DROP TABLE IF EXISTS call_import_schemas"))
    db.commit()
