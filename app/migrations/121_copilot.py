"""In-app copilot chat (EFF-71): sessions, messages, and workspace activity read indexes."""

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

description = "copilot_sessions, copilot_messages, copilot_actions; (workspace_id, created_at) indexes on eval tables"
MIGRATION_SCOPE = "catalog"

# Copilot answers "what ran this week" with per-workspace, per-period counts.
# Without these the planner falls back to the org index and filters in memory.
_ACTIVITY_INDEXES = (
    "CREATE INDEX {mode} IF NOT EXISTS ix_call_import_evaluations_ws_created "
    "ON call_import_evaluations (workspace_id, created_at DESC)",
    "CREATE INDEX {mode} IF NOT EXISTS ix_simulation_runs_ws_created "
    "ON simulation_runs (workspace_id, created_at DESC)",
    "CREATE INDEX {mode} IF NOT EXISTS ix_evaluator_results_ws_created "
    "ON evaluator_results (workspace_id, created_at DESC)",
    "CREATE INDEX {mode} IF NOT EXISTS ix_evaluations_ws_created "
    "ON evaluations (workspace_id, created_at DESC)",
)


def _build_activity_indexes(db: Session) -> None:
    """Build without holding the migration transaction (these tables are large)."""
    bind = db.get_bind()
    db.commit()
    if bind is not None and bind.dialect.name == "postgresql":
        try:
            with bind.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                for statement in _ACTIVITY_INDEXES:
                    conn.execute(text(statement.format(mode="CONCURRENTLY")))
            return
        except Exception as exc:
            logger.warning("concurrent copilot activity index build fell back: {}", exc)
    for statement in _ACTIVITY_INDEXES:
        db.execute(text(statement.format(mode="")))
    db.commit()


def upgrade(db: Session):
    db.execute(text("""
            CREATE TABLE IF NOT EXISTS copilot_sessions (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title VARCHAR(200),
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                draft JSON NOT NULL DEFAULT '{}',
                message_count INTEGER NOT NULL DEFAULT 0,
                last_message_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """))
    db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_copilot_sessions_user_ws_recent
                ON copilot_sessions (user_id, workspace_id, status, last_message_at, id)
            """))
    db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_copilot_sessions_org
                ON copilot_sessions (organization_id)
            """))
    db.execute(text("""
            CREATE TABLE IF NOT EXISTS copilot_messages (
                id UUID PRIMARY KEY,
                session_id UUID NOT NULL REFERENCES copilot_sessions(id) ON DELETE CASCADE,
                organization_id UUID NOT NULL,
                seq INTEGER NOT NULL,
                role VARCHAR(16) NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                steps JSON,
                status VARCHAR(16) NOT NULL DEFAULT 'complete',
                error TEXT,
                client_message_id UUID,
                page_context JSON,
                model VARCHAR(255),
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                latency_ms INTEGER,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ,
                CONSTRAINT uq_copilot_messages_session_seq UNIQUE (session_id, seq),
                CONSTRAINT uq_copilot_messages_session_client_id UNIQUE (session_id, client_message_id)
            )
            """))
    db.execute(text("""
            CREATE TABLE IF NOT EXISTS copilot_actions (
                id UUID PRIMARY KEY,
                session_id UUID NOT NULL REFERENCES copilot_sessions(id) ON DELETE CASCADE,
                organization_id UUID NOT NULL,
                workspace_id UUID NOT NULL,
                user_id UUID NOT NULL,
                message_id UUID,
                kind VARCHAR(64) NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'proposed',
                summary TEXT NOT NULL DEFAULT '',
                payload JSON NOT NULL DEFAULT '{}',
                cost_estimate JSON,
                result JSON,
                undo_state JSON,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMPTZ,
                decided_at TIMESTAMPTZ,
                undone_at TIMESTAMPTZ
            )
            """))
    db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_copilot_actions_session
                ON copilot_actions (session_id, created_at)
            """))
    db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_copilot_actions_workspace
                ON copilot_actions (workspace_id, created_at)
            """))
    db.commit()
    _build_activity_indexes(db)


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS copilot_actions"))
    db.execute(text("DROP TABLE IF EXISTS copilot_messages"))
    db.execute(text("DROP TABLE IF EXISTS copilot_sessions"))
    for name in (
        "ix_call_import_evaluations_ws_created",
        "ix_simulation_runs_ws_created",
        "ix_evaluator_results_ws_created",
        "ix_evaluations_ws_created",
    ):
        db.execute(text(f"DROP INDEX IF EXISTS {name}"))
    db.commit()
