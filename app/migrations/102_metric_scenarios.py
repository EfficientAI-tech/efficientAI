"""Link metrics to scenarios for scenario-scoped evaluation."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "metric_scenarios join table (scenario-scoped metrics)"
MIGRATION_SCOPE = "catalog"


def upgrade(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS metric_scenarios (
                metric_id UUID NOT NULL REFERENCES metrics(id) ON DELETE CASCADE,
                scenario_id UUID NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
                PRIMARY KEY (metric_id, scenario_id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_metric_scenarios_scenario_id
                ON metric_scenarios (scenario_id)
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS metric_scenarios"))
    db.commit()
