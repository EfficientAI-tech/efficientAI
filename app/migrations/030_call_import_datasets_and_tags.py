"""
Migration: Add dataset segregation and tags to call_imports.

Adds a free-text `dataset` column to call_imports (used as the
high-level filter on the imports page) and a separate many-to-many tag
system so a single import can also belong to multiple sub-categories.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add dataset column on call_imports plus call_import_tags m2m"


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return result.first() is not None


def _table_exists(db: Session, table_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
    )
    return result.first() is not None


def _index_exists(db: Session, index_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT 1
            FROM pg_indexes
            WHERE indexname = :index_name
            """
        ),
        {"index_name": index_name},
    )
    return result.first() is not None


def upgrade(db: Session):
    if not _column_exists(db, "call_imports", "dataset"):
        db.execute(text("ALTER TABLE call_imports ADD COLUMN dataset VARCHAR(255)"))
        print("Added call_imports.dataset column")
    else:
        print("call_imports.dataset already exists, skipping...")

    if not _index_exists(db, "ix_call_imports_org_dataset"):
        db.execute(
            text(
                "CREATE INDEX ix_call_imports_org_dataset "
                "ON call_imports(organization_id, dataset)"
            )
        )
        print("Created index ix_call_imports_org_dataset")

    if not _table_exists(db, "call_import_tags"):
        db.execute(
            text(
                """
                CREATE TABLE call_import_tags (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    name VARCHAR(255) NOT NULL,
                    color VARCHAR(32),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    CONSTRAINT uq_call_import_tag_org_name UNIQUE (organization_id, name)
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_call_import_tags_organization_id "
                "ON call_import_tags(organization_id)"
            )
        )
        print("Created call_import_tags table")
    else:
        print("call_import_tags table already exists, skipping...")

    if not _table_exists(db, "call_import_tag_assignments"):
        db.execute(
            text(
                """
                CREATE TABLE call_import_tag_assignments (
                    call_import_id UUID NOT NULL
                        REFERENCES call_imports(id) ON DELETE CASCADE,
                    tag_id UUID NOT NULL
                        REFERENCES call_import_tags(id) ON DELETE CASCADE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (call_import_id, tag_id)
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX ix_call_import_tag_assignments_tag_id "
                "ON call_import_tag_assignments(tag_id)"
            )
        )
        print("Created call_import_tag_assignments table")
    else:
        print("call_import_tag_assignments table already exists, skipping...")

    db.commit()
    print("Successfully added dataset/tag schema for call imports")


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS call_import_tag_assignments"))
    db.execute(text("DROP TABLE IF EXISTS call_import_tags"))
    db.execute(text("DROP INDEX IF EXISTS ix_call_imports_org_dataset"))
    if _column_exists(db, "call_imports", "dataset"):
        db.execute(text("ALTER TABLE call_imports DROP COLUMN dataset"))
    db.commit()
