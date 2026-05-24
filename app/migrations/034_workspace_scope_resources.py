"""
Migration: Workspace-scope the rest of the resource model.

Migration 033 created the ``workspaces`` table and backfilled
``metrics`` / ``call_imports`` / ``call_import_evaluations``. This
migration extends the same pattern to every other resource the user
interacts with directly:

  - Simulation building blocks: ``agents``, ``personas``, ``scenarios``
  - Playground state: ``test_agent_conversations``, ``call_recordings``
  - Evaluations (legacy + new): ``evaluations``, ``evaluation_results``,
    ``evaluators``, ``evaluator_results``
  - Voice Playground: ``tts_comparisons``, ``tts_samples``,
    ``tts_report_jobs``, ``tts_blind_test_shares``,
    ``tts_blind_test_responses``
  - Prompt tooling: ``prompt_partials``, ``prompt_partial_versions``,
    ``prompt_optimization_runs``, ``prompt_optimization_candidates``
  - Judge alignment: ``judge_datasets``, ``judge_samples``,
    ``judge_runs``

Each table is treated in one of two ways depending on whether it
already carries an ``organization_id``:

  * **Top-level rows** (have ``organization_id``): a new
    ``workspace_id`` column is added, backfilled to the org's
    Default workspace, then promoted to NOT NULL + FK + index.

  * **Child rows** (FK to a parent): ``workspace_id`` is added and
    backfilled by copying from the parent (denormalized for cheap
    workspace filtering on the listing endpoints).

Idempotent: each step checks for prior existence so reruns are safe.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add workspace_id to agents, personas, scenarios, evaluations, "
    "evaluation_results, evaluators, evaluator_results, call_recordings, "
    "test_agent_conversations, tts_* and prompt_* tables, and judge_* tables"
)


# ---------------------------------------------------------------------------
# Introspection helpers (Postgres information_schema)
# ---------------------------------------------------------------------------

def _table_exists(db: Session, table: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table},
    ).first()
    return row is not None


def _column_exists(db: Session, table: str, column: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table, "column_name": column},
    ).first()
    return row is not None


def _constraint_exists(db: Session, table: str, constraint: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM information_schema.table_constraints
            WHERE table_name = :table_name AND constraint_name = :constraint_name
            """
        ),
        {"table_name": table, "constraint_name": constraint},
    ).first()
    return row is not None


# ---------------------------------------------------------------------------
# Generic add/backfill primitives
# ---------------------------------------------------------------------------

def _add_nullable_workspace_id(db: Session, table: str) -> None:
    if _column_exists(db, table, "workspace_id"):
        print(f"{table}.workspace_id already exists, skipping ADD COLUMN")
        return
    db.execute(text(f"ALTER TABLE {table} ADD COLUMN workspace_id UUID NULL"))
    print(f"Added {table}.workspace_id (nullable)")


def _finalize_workspace_id(db: Session, table: str) -> None:
    """Promote workspace_id to NOT NULL and attach FK + index."""
    db.execute(
        text(f"ALTER TABLE {table} ALTER COLUMN workspace_id SET NOT NULL")
    )

    fk_name = f"fk_{table}_workspace_id"
    if not _constraint_exists(db, table, fk_name):
        db.execute(
            text(
                f"""
                ALTER TABLE {table}
                ADD CONSTRAINT {fk_name}
                FOREIGN KEY (workspace_id)
                REFERENCES workspaces(id) ON DELETE RESTRICT
                """
            )
        )
        print(f"Added FK {fk_name}")

    index_name = f"ix_{table}_workspace_id"
    db.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {table} (workspace_id)"
        )
    )


def _backfill_from_org_default(db: Session, table: str) -> None:
    """Backfill ``workspace_id`` from the org's Default workspace."""
    db.execute(
        text(
            f"""
            UPDATE {table} t
            SET workspace_id = w.id
            FROM workspaces w
            WHERE t.workspace_id IS NULL
              AND w.organization_id = t.organization_id
              AND w.is_default = TRUE
            """
        )
    )


def _backfill_from_parent(
    db: Session,
    *,
    table: str,
    parent_table: str,
    parent_fk_column: str,
) -> None:
    """Backfill child rows by copying workspace_id from the parent row."""
    db.execute(
        text(
            f"""
            UPDATE {table} child
            SET workspace_id = parent.workspace_id
            FROM {parent_table} parent
            WHERE child.workspace_id IS NULL
              AND parent.id = child.{parent_fk_column}
              AND parent.workspace_id IS NOT NULL
            """
        )
    )


# ---------------------------------------------------------------------------
# Convenience wrappers per "shape"
# ---------------------------------------------------------------------------

def _scope_from_org(db: Session, table: str) -> None:
    """Full pipeline for a top-level (org-scoped) table."""
    if not _table_exists(db, table):
        print(f"Table {table} does not exist, skipping")
        return
    _add_nullable_workspace_id(db, table)
    _backfill_from_org_default(db, table)
    _finalize_workspace_id(db, table)
    db.commit()
    print(f"✓ workspace_id ready on {table}")


def _scope_from_parent(
    db: Session,
    *,
    table: str,
    parent_table: str,
    parent_fk_column: str,
) -> None:
    """Full pipeline for a child table that mirrors its parent."""
    if not _table_exists(db, table):
        print(f"Table {table} does not exist, skipping")
        return
    _add_nullable_workspace_id(db, table)
    _backfill_from_parent(
        db,
        table=table,
        parent_table=parent_table,
        parent_fk_column=parent_fk_column,
    )
    _finalize_workspace_id(db, table)
    db.commit()
    print(f"✓ workspace_id ready on {table} (mirrors {parent_table})")


def _scope_call_recordings(db: Session) -> None:
    """Special case for ``call_recordings``.

    A recording is either tied to an agent (playground / observability
    flows) or floats free under the org (legacy / unbound webhooks).
    We prefer the agent's workspace when there is one so recordings
    stay co-located with the agent that produced them, and fall back
    to the org default otherwise.
    """
    table = "call_recordings"
    if not _table_exists(db, table):
        print(f"Table {table} does not exist, skipping")
        return

    _add_nullable_workspace_id(db, table)

    # 1) Pull workspace from the linked agent when present.
    db.execute(
        text(
            """
            UPDATE call_recordings cr
            SET workspace_id = a.workspace_id
            FROM agents a
            WHERE cr.workspace_id IS NULL
              AND cr.agent_id = a.id
              AND a.workspace_id IS NOT NULL
            """
        )
    )

    # 2) Anything still unset (no agent / agent had no workspace yet)
    #    falls back to the org's Default workspace.
    _backfill_from_org_default(db, table)

    _finalize_workspace_id(db, table)
    db.commit()
    print("✓ workspace_id ready on call_recordings")


# ---------------------------------------------------------------------------
# Migration entrypoints
# ---------------------------------------------------------------------------

def upgrade(db: Session):
    if not _table_exists(db, "workspaces"):
        raise RuntimeError(
            "Migration 034 requires the workspaces table from migration 033. "
            "Run migration 033 first."
        )

    # Top-level org-scoped tables. Order matters when a child depends
    # on a parent in this same migration (e.g. evaluation_results needs
    # evaluations to be done, tts_samples needs tts_comparisons).
    for table in (
        "agents",
        "personas",
        "scenarios",
        "evaluations",
        "evaluators",
        "evaluator_results",
        "test_agent_conversations",
        "tts_comparisons",
        "tts_report_jobs",
        "tts_blind_test_shares",
        "prompt_partials",
        "prompt_optimization_runs",
        "judge_datasets",
        "judge_runs",
    ):
        _scope_from_org(db, table)

    # Child tables that mirror their parent's workspace_id.
    _scope_from_parent(
        db,
        table="evaluation_results",
        parent_table="evaluations",
        parent_fk_column="evaluation_id",
    )
    _scope_from_parent(
        db,
        table="tts_samples",
        parent_table="tts_comparisons",
        parent_fk_column="comparison_id",
    )
    _scope_from_parent(
        db,
        table="tts_blind_test_responses",
        parent_table="tts_blind_test_shares",
        parent_fk_column="share_id",
    )
    _scope_from_parent(
        db,
        table="prompt_partial_versions",
        parent_table="prompt_partials",
        parent_fk_column="prompt_partial_id",
    )
    _scope_from_parent(
        db,
        table="prompt_optimization_candidates",
        parent_table="prompt_optimization_runs",
        parent_fk_column="optimization_run_id",
    )
    _scope_from_parent(
        db,
        table="judge_samples",
        parent_table="judge_datasets",
        parent_fk_column="dataset_id",
    )

    # call_recordings has its own hybrid backfill (agent → org default).
    _scope_call_recordings(db)

    print("All resource tables are now workspace-scoped")


def downgrade(db: Session):
    # Drop in reverse dependency order (children before parents).
    for table in (
        "call_recordings",
        "judge_samples",
        "prompt_optimization_candidates",
        "prompt_partial_versions",
        "tts_blind_test_responses",
        "tts_samples",
        "evaluation_results",
        "judge_runs",
        "judge_datasets",
        "prompt_optimization_runs",
        "prompt_partials",
        "tts_blind_test_shares",
        "tts_report_jobs",
        "tts_comparisons",
        "test_agent_conversations",
        "evaluator_results",
        "evaluators",
        "evaluations",
        "scenarios",
        "personas",
        "agents",
    ):
        fk_name = f"fk_{table}_workspace_id"
        db.execute(
            text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {fk_name}")
        )
        db.execute(
            text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS workspace_id")
        )
    db.commit()
