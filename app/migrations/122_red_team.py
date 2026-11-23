"""Red teaming (EFF-36): red_team_runs and red_team_attacks."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add red_team_runs and red_team_attacks tables"
MIGRATION_SCOPE = "all"


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if not _table_exists(db, "red_team_runs"):
        db.execute(
            text(
                """
                CREATE TABLE red_team_runs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    run_id VARCHAR(6) NOT NULL UNIQUE,
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    name VARCHAR NULL,
                    intensity VARCHAR(16) NOT NULL,
                    modality VARCHAR(16) NOT NULL,
                    config JSON NOT NULL DEFAULT '{}',
                    attacker_knowledge JSON NULL,
                    connection_overrides JSON NULL,
                    persona_id UUID NULL REFERENCES personas(id) ON DELETE SET NULL,
                    attacker_llm_provider VARCHAR(64) NULL,
                    attacker_llm_model VARCHAR(255) NULL,
                    judge_llm_provider VARCHAR(64) NULL,
                    judge_llm_model VARCHAR(255) NULL,
                    resolved_llms JSON NULL,
                    catalog_version VARCHAR(16) NOT NULL,
                    agent_profile JSON NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'queued',
                    verdict VARCHAR(32) NULL,
                    report JSON NULL,
                    max_attacks INTEGER NOT NULL DEFAULT 0,
                    completed_attacks INTEGER NOT NULL DEFAULT 0,
                    breached_attacks INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT NULL,
                    celery_task_id VARCHAR NULL,
                    cancel_requested BOOLEAN NOT NULL DEFAULT false,
                    started_at TIMESTAMPTZ NULL,
                    finished_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR NULL
                )
                """
            )
        )
        for column in ("organization_id", "workspace_id", "agent_id", "status"):
            db.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_red_team_runs_{column} "
                    f"ON red_team_runs ({column})"
                )
            )

    if not _table_exists(db, "red_team_attacks"):
        db.execute(
            text(
                """
                CREATE TABLE red_team_attacks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    red_team_run_id UUID NOT NULL REFERENCES red_team_runs(id) ON DELETE CASCADE,
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    parent_attack_id UUID NULL REFERENCES red_team_attacks(id) ON DELETE SET NULL,
                    kind VARCHAR(16) NOT NULL DEFAULT 'attack',
                    level INTEGER NOT NULL DEFAULT 0,
                    sequence INTEGER NOT NULL DEFAULT 0,
                    family VARCHAR(32) NULL,
                    technique_id VARCHAR(64) NULL,
                    owasp_category VARCHAR(8) NULL,
                    harm_category VARCHAR(32) NULL,
                    goal TEXT NULL,
                    strategy TEXT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'queued',
                    outcome VARCHAR(16) NULL,
                    score DOUBLE PRECISION NULL,
                    success_score DOUBLE PRECISION NULL,
                    judge JSON NULL,
                    transcript JSON NULL,
                    evaluator_result_id UUID NULL REFERENCES evaluator_results(id) ON DELETE SET NULL,
                    error_message TEXT NULL,
                    started_at TIMESTAMPTZ NULL,
                    finished_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        for column in ("red_team_run_id", "organization_id", "parent_attack_id"):
            db.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_red_team_attacks_{column} "
                    f"ON red_team_attacks ({column})"
                )
            )
    db.commit()
