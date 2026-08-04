"""
Migration: Evaluator suites — group agent + persona + N scenarios.

Creates ``evaluator_suites`` table, adds ``suite_id`` to evaluators, and
backfills one suite per existing standard evaluator row.
"""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add evaluator_suites table and suite_id on evaluators"


def _json_bind(value):
    """Serialize Python values for PostgreSQL JSON columns."""
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        return value
    return json.dumps(value)


def _table_exists(db: Session, table_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
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
                SELECT 1 FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = :column_name
            )
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


def upgrade(db: Session):
    if not _table_exists(db, "evaluator_suites"):
        db.execute(
            text(
                """
                CREATE TABLE evaluator_suites (
                    id UUID PRIMARY KEY,
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                    name VARCHAR NULL,
                    agent_id UUID NOT NULL REFERENCES agents(id),
                    persona_id UUID NOT NULL REFERENCES personas(id),
                    metric_ids JSON NULL,
                    llm_provider VARCHAR NULL,
                    llm_model VARCHAR NULL,
                    llm_config JSON NULL,
                    tags JSON NULL,
                    default_runs_per_combination INTEGER NOT NULL DEFAULT 1,
                    round_robin_index INTEGER NOT NULL DEFAULT 0,
                    is_active BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR NULL
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_evaluator_suites_org "
                "ON evaluator_suites (organization_id)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_evaluator_suites_workspace "
                "ON evaluator_suites (workspace_id)"
            )
        )

    if _table_exists(db, "evaluators") and not _column_exists(db, "evaluators", "suite_id"):
        db.execute(
            text(
                """
                ALTER TABLE evaluators
                ADD COLUMN suite_id UUID NULL REFERENCES evaluator_suites(id) ON DELETE CASCADE
                """
            )
        )
        db.execute(
            text("CREATE INDEX IF NOT EXISTS ix_evaluators_suite_id ON evaluators (suite_id)")
        )

    if _table_exists(db, "evaluators") and _column_exists(db, "evaluators", "suite_id"):
        rows = db.execute(
            text(
                """
                SELECT id, organization_id, workspace_id, name, agent_id, persona_id,
                       metric_ids, llm_provider, llm_model, llm_config, tags, created_by
                FROM evaluators
                WHERE agent_id IS NOT NULL
                  AND persona_id IS NOT NULL
                  AND scenario_id IS NOT NULL
                  AND suite_id IS NULL
                """
            )
        ).fetchall()

        suite_has_is_active = _column_exists(db, "evaluator_suites", "is_active")

        for row in rows:
            suite_id = uuid.uuid4()
            if suite_has_is_active:
                insert_sql = """
                    INSERT INTO evaluator_suites (
                        id, organization_id, workspace_id, name, agent_id, persona_id,
                        metric_ids, llm_provider, llm_model, llm_config, tags,
                        default_runs_per_combination, round_robin_index, is_active, created_by
                    ) VALUES (
                        :id, :organization_id, :workspace_id, :name, :agent_id, :persona_id,
                        :metric_ids, :llm_provider, :llm_model, :llm_config, :tags,
                        1, 0, FALSE, :created_by
                    )
                """
            else:
                insert_sql = """
                    INSERT INTO evaluator_suites (
                        id, organization_id, workspace_id, name, agent_id, persona_id,
                        metric_ids, llm_provider, llm_model, llm_config, tags,
                        default_runs_per_combination, round_robin_index, created_by
                    ) VALUES (
                        :id, :organization_id, :workspace_id, :name, :agent_id, :persona_id,
                        :metric_ids, :llm_provider, :llm_model, :llm_config, :tags,
                        1, 0, :created_by
                    )
                """
            db.execute(
                text(insert_sql),
                {
                    "id": suite_id,
                    "organization_id": row[1],
                    "workspace_id": row[2],
                    "name": row[3],
                    "agent_id": row[4],
                    "persona_id": row[5],
                    "metric_ids": _json_bind(row[6]),
                    "llm_provider": row[7],
                    "llm_model": row[8],
                    "llm_config": _json_bind(row[9]),
                    "tags": _json_bind(row[10]),
                    "created_by": row[11],
                },
            )
            db.execute(
                text("UPDATE evaluators SET suite_id = :suite_id WHERE id = :evaluator_id"),
                {"suite_id": suite_id, "evaluator_id": row[0]},
            )

    db.commit()


def downgrade(db: Session):
    if _table_exists(db, "evaluators") and _column_exists(db, "evaluators", "suite_id"):
        db.execute(text("ALTER TABLE evaluators DROP COLUMN suite_id"))
    if _table_exists(db, "evaluator_suites"):
        db.execute(text("DROP TABLE evaluator_suites"))
    db.commit()
