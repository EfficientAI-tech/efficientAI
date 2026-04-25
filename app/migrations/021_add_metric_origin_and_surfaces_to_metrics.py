"""
Migration: Add metric_origin and surface configuration columns to metrics table.

Backfills existing installations whose `metrics` table was created before the
following columns were added to the SQLAlchemy model:
    - metric_origin (String(30), NOT NULL, default 'default')
    - supported_surfaces (JSON, NOT NULL, default [])
    - enabled_surfaces (JSON, NOT NULL, default [])
    - custom_data_type (String(30), nullable)
    - custom_config (JSON, nullable)
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add metric_origin, supported_surfaces, enabled_surfaces, custom_data_type, custom_config to metrics"


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
    if not _table_exists(db, "metrics"):
        # Nothing to backfill; table will be created by SQLAlchemy from the model.
        db.commit()
        return

    if not _column_exists(db, "metrics", "metric_origin"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN metric_origin VARCHAR(30) NOT NULL DEFAULT 'default'
                """
            )
        )
        # Existing default-seeded metrics should remain marked as 'default';
        # any rows that were created via the API with is_default=false should
        # be reclassified as 'custom' to match new application semantics.
        db.execute(
            text(
                """
                UPDATE metrics
                SET metric_origin = 'custom'
                WHERE is_default = FALSE
                """
            )
        )

    if not _column_exists(db, "metrics", "supported_surfaces"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN supported_surfaces JSON NOT NULL DEFAULT '[]'::json
                """
            )
        )
        # Best-effort backfill: assume pre-existing metrics were used on the
        # agent surface so they keep behaving as before.
        db.execute(
            text(
                """
                UPDATE metrics
                SET supported_surfaces = '["agent"]'::json
                WHERE supported_surfaces::text = '[]'
                """
            )
        )

    if not _column_exists(db, "metrics", "enabled_surfaces"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN enabled_surfaces JSON NOT NULL DEFAULT '[]'::json
                """
            )
        )
        db.execute(
            text(
                """
                UPDATE metrics
                SET enabled_surfaces = CASE
                    WHEN enabled = TRUE THEN '["agent"]'::json
                    ELSE '[]'::json
                END
                WHERE enabled_surfaces::text = '[]'
                """
            )
        )

    if not _column_exists(db, "metrics", "custom_data_type"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN custom_data_type VARCHAR(30)
                """
            )
        )

    if not _column_exists(db, "metrics", "custom_config"):
        db.execute(
            text(
                """
                ALTER TABLE metrics
                ADD COLUMN custom_config JSON
                """
            )
        )

    db.commit()


def downgrade(db: Session):
    if not _table_exists(db, "metrics"):
        db.commit()
        return

    for column in (
        "custom_config",
        "custom_data_type",
        "enabled_surfaces",
        "supported_surfaces",
        "metric_origin",
    ):
        if _column_exists(db, "metrics", column):
            db.execute(text(f"ALTER TABLE metrics DROP COLUMN {column}"))

    db.commit()
