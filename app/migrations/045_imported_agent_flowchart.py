"""Migration: Cache agent flowcharts on prompt partials for imported agents."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add agent_flowchart and agent_flowchart_status to prompt_partials."


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
    if not _column_exists(db, "prompt_partials", "agent_flowchart"):
        db.execute(text("ALTER TABLE prompt_partials ADD COLUMN agent_flowchart JSON"))
        print("Added prompt_partials.agent_flowchart")
    else:
        print("prompt_partials.agent_flowchart already exists, skipping")

    if not _column_exists(db, "prompt_partials", "agent_flowchart_status"):
        db.execute(
            text(
                "ALTER TABLE prompt_partials ADD COLUMN agent_flowchart_status VARCHAR(20)"
            )
        )
        print("Added prompt_partials.agent_flowchart_status")
    else:
        print("prompt_partials.agent_flowchart_status already exists, skipping")


def downgrade(db: Session):
    if _column_exists(db, "prompt_partials", "agent_flowchart_status"):
        db.execute(
            text("ALTER TABLE prompt_partials DROP COLUMN agent_flowchart_status")
        )
        print("Dropped prompt_partials.agent_flowchart_status")
    if _column_exists(db, "prompt_partials", "agent_flowchart"):
        db.execute(text("ALTER TABLE prompt_partials DROP COLUMN agent_flowchart"))
        print("Dropped prompt_partials.agent_flowchart")
