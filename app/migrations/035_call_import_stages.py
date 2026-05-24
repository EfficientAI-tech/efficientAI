"""
Migration: Idempotent UPLOADED / MAPPED / PROCESSING stages for call imports.

Splits the previous monolithic upload (file + mapping + provider + rows +
worker enqueue in one POST) into three independent stages:

  1. UPLOAD  -- file is persisted to S3 and the batch is stamped as
                ``status='uploaded'`` with the file's discovered sheets /
                headers cached on the row. Dataset + tags are collected
                up-front. No telephony credential is needed yet.
  2. MAP     -- the user picks a schema and sheet, supplies a
                ``parameter_mapping`` + ``skipped_columns`` payload, and
                the batch transitions to ``status='mapped'``. Re-running
                this endpoint while already mapped is allowed (the
                mapping is updated in place).
  3. IMPORT  -- the user picks a telephony provider + credential. We
                re-fetch the stored file from S3, materialise
                ``call_import_rows``, and enqueue the existing
                ``process_call_import_row_task`` workers (the rest of
                the pipeline is unchanged).

To support that, we:

  * Add ``source_s3_key``, ``source_format``, ``source_size_bytes``,
    ``source_content_type``, ``available_sheets`` and
    ``skipped_columns`` columns on ``call_imports`` so each stage can
    be resumed without re-uploading the file.
  * Relax the NOT NULL on ``call_imports.provider`` (the IMPORT stage
    is the first step that knows the provider). The historical default
    of ``'exotel'`` is left in place at the SQL level so legacy clients
    that hit the deprecated ``POST /upload`` endpoint without supplying
    a provider continue to work.

The status enum is enforced application-side (``CallImportStatus``);
the DB stores it as a ``VARCHAR(20)`` so adding the new ``uploaded`` /
``mapped`` values is purely a Python-side change. No ``ALTER TYPE``
needed here.

Idempotent: every step checks for prior state before applying.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add source-file + mapping columns on call_imports and relax "
    "provider nullability so UPLOADED/MAPPED/PROCESSING can be three "
    "independent stages."
)


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def _column_is_nullable(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    if row is None:
        return False
    return (row[0] or "").upper() == "YES"


def upgrade(db: Session):
    # 1. Source-file columns (where the raw upload lives in S3 between
    # stages). All nullable so legacy batches imported before this
    # migration keep working as read-only records.
    if not _column_exists(db, "call_imports", "source_s3_key"):
        db.execute(
            text(
                "ALTER TABLE call_imports ADD COLUMN source_s3_key TEXT NULL"
            )
        )
        print("Added call_imports.source_s3_key")
    else:
        print("call_imports.source_s3_key already exists, skipping...")

    if not _column_exists(db, "call_imports", "source_format"):
        db.execute(
            text(
                "ALTER TABLE call_imports ADD COLUMN source_format VARCHAR(16) NULL"
            )
        )
        print("Added call_imports.source_format")
    else:
        print("call_imports.source_format already exists, skipping...")

    if not _column_exists(db, "call_imports", "source_size_bytes"):
        db.execute(
            text(
                "ALTER TABLE call_imports ADD COLUMN source_size_bytes BIGINT NULL"
            )
        )
        print("Added call_imports.source_size_bytes")
    else:
        print("call_imports.source_size_bytes already exists, skipping...")

    if not _column_exists(db, "call_imports", "source_content_type"):
        db.execute(
            text(
                "ALTER TABLE call_imports "
                "ADD COLUMN source_content_type VARCHAR(255) NULL"
            )
        )
        print("Added call_imports.source_content_type")
    else:
        print("call_imports.source_content_type already exists, skipping...")

    # 2. Sheet snapshot captured at UPLOAD time so the MAP stage can
    # render headers without re-fetching the file from S3. Shape:
    # [{"name": str, "headers": [str, ...], "row_count": int}, ...].
    if not _column_exists(db, "call_imports", "available_sheets"):
        db.execute(
            text(
                "ALTER TABLE call_imports ADD COLUMN available_sheets JSONB NULL"
            )
        )
        print("Added call_imports.available_sheets")
    else:
        print("call_imports.available_sheets already exists, skipping...")

    # 3. The user's explicit "drop these columns" decision. Was
    # validation-only and ephemeral before; now persisted so the IMPORT
    # stage can re-parse the file with the same intent the user
    # captured during MAP.
    if not _column_exists(db, "call_imports", "skipped_columns"):
        db.execute(
            text(
                "ALTER TABLE call_imports "
                "ADD COLUMN skipped_columns JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        )
        print("Added call_imports.skipped_columns")
    else:
        print("call_imports.skipped_columns already exists, skipping...")

    # 4. Provider is now learnt at the IMPORT stage, not at UPLOAD, so
    # the column has to allow NULLs. We keep the historical SQL default
    # of ``'exotel'`` so existing clients hitting the deprecated
    # one-shot ``POST /upload`` endpoint without an explicit provider
    # still get the old behaviour.
    if _column_exists(db, "call_imports", "provider") and not _column_is_nullable(
        db, "call_imports", "provider"
    ):
        db.execute(
            text("ALTER TABLE call_imports ALTER COLUMN provider DROP NOT NULL")
        )
        print("Relaxed call_imports.provider to allow NULL")
    else:
        print(
            "call_imports.provider already nullable (or column missing), "
            "skipping..."
        )

    db.commit()
    print("call_import stages schema is in place")


def downgrade(db: Session):
    # Tighten provider back to NOT NULL using the historical 'exotel'
    # default for any rows that have NULL because they were created
    # during the staged flow.
    if _column_exists(db, "call_imports", "provider") and _column_is_nullable(
        db, "call_imports", "provider"
    ):
        db.execute(
            text(
                "UPDATE call_imports SET provider = 'exotel' WHERE provider IS NULL"
            )
        )
        db.execute(
            text("ALTER TABLE call_imports ALTER COLUMN provider SET NOT NULL")
        )

    for column in (
        "skipped_columns",
        "available_sheets",
        "source_content_type",
        "source_size_bytes",
        "source_format",
        "source_s3_key",
    ):
        if _column_exists(db, "call_imports", column):
            db.execute(text(f"ALTER TABLE call_imports DROP COLUMN {column}"))

    db.commit()
