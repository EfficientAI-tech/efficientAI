"""
Migration: Allow metrics to be scoped at the organization level (shared
across every workspace in the org) in addition to the existing
workspace-scoped behavior.

Changes:
  * ``metrics.workspace_id`` becomes nullable. ``NULL`` means the metric
    is org-shared and shows up in every workspace's listing.
  * Adds two helper indexes for the read-path:
      - ``ix_metrics_org_ws_parent_name`` covers the workspace-scoped
        rows (matches the existing duplicate-name lookup in
        ``create_metric``).
      - ``ix_metrics_org_parent_name_shared`` covers the org-shared
        rows (the new bucket).
    These are NOT ``UNIQUE`` indexes — historically the metrics table
    has never had a DB-level uniqueness constraint on
    ``(org, workspace, parent, name)``; duplicate prevention has always
    been enforced by the application layer (see the duplicate-name
    check inside ``create_metric``). Adding ``UNIQUE`` here would fail
    on existing orgs whose data was created before the app-level check
    landed (or under races), so we keep parity with the old behavior.
  * Adds ``ix_metrics_org_shared`` (partial, ``WHERE workspace_id IS
    NULL``) so the union listing query can hit the org-shared half
    without scanning every row in the org.

Existing rows are NOT touched - every metric created before this
migration keeps its current ``workspace_id`` and so retains its
workspace-scoped behavior.

Idempotent: every step checks for prior state before applying.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Make metrics.workspace_id nullable and add three helper indexes "
    "(workspace-scoped lookup, org-shared lookup, org-shared partial "
    "scan helper) for the dual-scope listing query."
)


# Index names — kept in one place so upgrade/downgrade stay symmetric.
_IDX_WS_SCOPED = "ix_metrics_org_ws_parent_name"
_IDX_ORG_SHARED = "ix_metrics_org_parent_name_shared"
_IDX_ORG_SHARED_LOOKUP = "ix_metrics_org_shared"


def _column_is_nullable(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    if row is None:
        return False
    return str(row[0]).upper() == "YES"


def _index_exists(db: Session, index_name: str) -> bool:
    row = db.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :index_name"),
        {"index_name": index_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    # 1. Drop NOT NULL on metrics.workspace_id so org-shared rows can
    #    persist with NULL. Idempotent: skip when already nullable.
    if not _column_is_nullable(db, "metrics", "workspace_id"):
        db.execute(
            text("ALTER TABLE metrics ALTER COLUMN workspace_id DROP NOT NULL")
        )
        print("Made metrics.workspace_id nullable")
    else:
        print("metrics.workspace_id is already nullable, skipping")

    # 2. Helper indexes for the duplicate-name lookups in
    #    ``create_metric`` and the ``list_metrics`` union query. Both
    #    are partial (``WHERE workspace_id IS / IS NOT NULL``) so each
    #    one only covers the half of the table it actually serves.
    #
    #    These are intentionally NON-UNIQUE: the metrics table has
    #    historically never had a DB-level uniqueness constraint on
    #    (org, workspace, parent, name) — duplicate prevention has
    #    always lived in the application layer (the ``existing``
    #    lookup at the top of ``create_metric``). Some orgs already
    #    have duplicate rows from before that check landed (or from
    #    racy concurrent writes), so promoting these to ``UNIQUE``
    #    would break the migration with an IntegrityError on existing
    #    data. We keep the historical behavior and rely on the app
    #    check for write-time enforcement.
    if not _index_exists(db, _IDX_WS_SCOPED):
        db.execute(
            text(
                f"""
                CREATE INDEX {_IDX_WS_SCOPED}
                ON metrics (organization_id, workspace_id, parent_metric_id, name)
                WHERE workspace_id IS NOT NULL
                """
            )
        )
        print(f"Created partial index {_IDX_WS_SCOPED}")
    else:
        print(f"{_IDX_WS_SCOPED} already exists, skipping")

    if not _index_exists(db, _IDX_ORG_SHARED):
        db.execute(
            text(
                f"""
                CREATE INDEX {_IDX_ORG_SHARED}
                ON metrics (organization_id, parent_metric_id, name)
                WHERE workspace_id IS NULL
                """
            )
        )
        print(f"Created partial index {_IDX_ORG_SHARED}")
    else:
        print(f"{_IDX_ORG_SHARED} already exists, skipping")

    # 3. Lookup helper for the union list query
    #    ``WHERE workspace_id = :ws OR workspace_id IS NULL``. The
    #    workspace half is already covered by ``ix_metrics_org_workspace``
    #    (created by 033_workspaces.py); this partial index covers the
    #    org-shared half so we don't have to scan the whole org.
    if not _index_exists(db, _IDX_ORG_SHARED_LOOKUP):
        db.execute(
            text(
                f"""
                CREATE INDEX {_IDX_ORG_SHARED_LOOKUP}
                ON metrics (organization_id)
                WHERE workspace_id IS NULL
                """
            )
        )
        print(f"Created partial index {_IDX_ORG_SHARED_LOOKUP}")
    else:
        print(f"{_IDX_ORG_SHARED_LOOKUP} already exists, skipping")

    db.commit()
    print("Org-shared metrics schema is in place")


def downgrade(db: Session):
    # 1. Drop the two partial indexes + the org-shared lookup helper.
    for index_name in (_IDX_ORG_SHARED_LOOKUP, _IDX_ORG_SHARED, _IDX_WS_SCOPED):
        db.execute(text(f"DROP INDEX IF EXISTS {index_name}"))

    # 2. Backfill any org-shared rows (workspace_id IS NULL) to each
    #    org's Default workspace so the NOT NULL constraint can be
    #    re-applied without violating the FK.
    db.execute(
        text(
            """
            UPDATE metrics m
            SET workspace_id = w.id
            FROM workspaces w
            WHERE w.organization_id = m.organization_id
              AND w.is_default IS TRUE
              AND m.workspace_id IS NULL
            """
        )
    )

    # 3. Restore the NOT NULL constraint. Skip when no NULLs remain and
    #    the column is already NOT NULL (idempotent re-runs).
    leftover = db.execute(
        text("SELECT COUNT(*) FROM metrics WHERE workspace_id IS NULL")
    ).scalar()
    if leftover and leftover > 0:
        raise RuntimeError(
            "Cannot restore NOT NULL on metrics.workspace_id: "
            f"{leftover} org-shared metric row(s) could not be backfilled "
            "(no Default workspace for their org?)."
        )
    if _column_is_nullable(db, "metrics", "workspace_id"):
        db.execute(
            text("ALTER TABLE metrics ALTER COLUMN workspace_id SET NOT NULL")
        )

    db.commit()
