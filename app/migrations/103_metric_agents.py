"""Link metrics to agents for agent-scoped evaluation."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "metric_agents join table (agent-scoped metrics)"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS metric_agents (
                metric_id UUID NOT NULL REFERENCES metrics(id) ON DELETE CASCADE,
                agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                PRIMARY KEY (metric_id, agent_id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_metric_agents_agent_id
                ON metric_agents (agent_id)
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS metric_agents"))
    db.commit()
