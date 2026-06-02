"""Migration: Normalize report-branding image roles.

Branding images are stored as JSON metadata on ``workspaces.report_branding``.
This migration is intentionally idempotent: it adds ``role='generic'`` to any
existing image objects that predate the two-logo external report workflow.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add generic roles to existing report branding image metadata."


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


def upgrade(db: Session):
    if not _column_exists(db, "workspaces", "report_branding"):
        print("workspaces.report_branding missing, skipping image role normalization")
        return

    db.execute(
        text(
            """
            UPDATE workspaces
            SET report_branding = jsonb_set(
                report_branding::jsonb,
                '{images}',
                (
                    SELECT jsonb_agg(
                        CASE
                            WHEN image ? 'role' THEN image
                            ELSE image || '{"role": "generic"}'::jsonb
                        END
                    )
                    FROM jsonb_array_elements(report_branding::jsonb->'images') AS image
                ),
                true
            )
            WHERE report_branding IS NOT NULL
              AND jsonb_typeof(report_branding::jsonb->'images') = 'array'
            """
        )
    )
    db.commit()
    print("Normalized report_branding image roles")


def downgrade(db: Session):
    if not _column_exists(db, "workspaces", "report_branding"):
        return
    db.execute(
        text(
            """
            UPDATE workspaces
            SET report_branding = jsonb_set(
                report_branding::jsonb,
                '{images}',
                (
                    SELECT jsonb_agg(image - 'role')
                    FROM jsonb_array_elements(report_branding::jsonb->'images') AS image
                ),
                true
            )
            WHERE report_branding IS NOT NULL
              AND jsonb_typeof(report_branding::jsonb->'images') = 'array'
            """
        )
    )
    db.commit()
