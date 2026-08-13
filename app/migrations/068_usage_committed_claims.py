"""Migration: usage_committed_claims for durable flush idempotency."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Create usage_committed_claims when missing (063 may have run before this table was added)"
)


def _table_exists(db: Session, table: str) -> bool:
    return (
        db.execute(
            text(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_name = :table_name
                """
            ),
            {"table_name": table},
        ).first()
        is not None
    )


def upgrade(db: Session):
    if _table_exists(db, "usage_committed_claims"):
        print("usage_committed_claims already exists, skipping 068")
        db.commit()
        return

    db.execute(
        text(
            """
            CREATE TABLE usage_committed_claims (
                claim_key TEXT PRIMARY KEY,
                organization_id UUID NOT NULL,
                committed_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX ix_usage_committed_claims_committed_at
            ON usage_committed_claims (committed_at)
            """
        )
    )
    print("Created usage_committed_claims")
    db.commit()


def downgrade(db: Session):
    db.execute(text("DROP TABLE IF EXISTS usage_committed_claims"))
    db.commit()
