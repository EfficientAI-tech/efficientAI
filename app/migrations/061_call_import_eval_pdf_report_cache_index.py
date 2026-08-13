"""Migration: PDF report cache fingerprint column rename and lookup index."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Rename config_fingerprint to cache_fingerprint and add unique "
    "(evaluation_id, cache_fingerprint) for scale-safe cache lookups"
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


def _column_exists(db: Session, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'call_import_evaluation_pdf_reports'
              AND column_name = :column_name
            """
        ),
        {"column_name": column_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _table_exists(db, "call_import_evaluation_pdf_reports"):
        print("call_import_evaluation_pdf_reports missing, skipping 061")
        db.commit()
        return

    if _column_exists(db, "config_fingerprint") and not _column_exists(
        db, "cache_fingerprint"
    ):
        db.execute(
            text(
                """
                ALTER TABLE call_import_evaluation_pdf_reports
                RENAME COLUMN config_fingerprint TO cache_fingerprint
                """
            )
        )
        print("Renamed config_fingerprint -> cache_fingerprint")

    if not _column_exists(db, "cache_fingerprint"):
        print("cache_fingerprint column missing, skipping index work")
        db.commit()
        return

    db.execute(
        text(
            """
            DELETE FROM call_import_evaluation_pdf_reports stale
            USING call_import_evaluation_pdf_reports keep
            WHERE stale.evaluation_id = keep.evaluation_id
              AND stale.cache_fingerprint = keep.cache_fingerprint
              AND stale.cache_fingerprint IS NOT NULL
              AND stale.id <> keep.id
              AND (
                stale.created_at < keep.created_at
                OR (
                    stale.created_at = keep.created_at
                    AND stale.id::text < keep.id::text
                )
              )
            """
        )
    )

    db.execute(
        text(
            """
            DROP INDEX IF EXISTS ix_call_import_eval_pdf_reports_fingerprint
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            uq_call_import_eval_pdf_reports_eval_cache_fp
            ON call_import_evaluation_pdf_reports (evaluation_id, cache_fingerprint)
            WHERE cache_fingerprint IS NOT NULL
            """
        )
    )
    print("Ensured unique (evaluation_id, cache_fingerprint) index")
    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "call_import_evaluation_pdf_reports"):
        db.commit()
        return

    db.execute(
        text(
            """
            DROP INDEX IF EXISTS uq_call_import_eval_pdf_reports_eval_cache_fp
            """
        )
    )
    if _column_exists(db, "cache_fingerprint") and not _column_exists(
        db, "config_fingerprint"
    ):
        db.execute(
            text(
                """
                ALTER TABLE call_import_evaluation_pdf_reports
                RENAME COLUMN cache_fingerprint TO config_fingerprint
                """
            )
        )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_call_import_eval_pdf_reports_fingerprint
            ON call_import_evaluation_pdf_reports (config_fingerprint)
            """
        )
    )
    db.commit()
