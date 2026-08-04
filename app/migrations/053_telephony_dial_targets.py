"""Migration: org-scoped saved outbound dial targets."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add telephony_dial_targets for org-level saved outbound destination numbers."


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def upgrade(db: Session):
    if _table_exists(db, "telephony_dial_targets"):
        print("telephony_dial_targets already exists, skipping...")
        return

    db.execute(
        text(
            """
            CREATE TABLE telephony_dial_targets (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                phone_number VARCHAR(20) NOT NULL,
                label VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                CONSTRAINT uq_telephony_dial_target_org_phone UNIQUE (organization_id, phone_number)
            )
            """
        )
    )
    db.execute(
        text(
            "CREATE INDEX ix_telephony_dial_targets_organization_id "
            "ON telephony_dial_targets(organization_id)"
        )
    )
    db.execute(
        text(
            "CREATE INDEX ix_telephony_dial_targets_phone_number "
            "ON telephony_dial_targets(phone_number)"
        )
    )
    db.commit()
    print("Created telephony_dial_targets table.")


def downgrade(db: Session):
    if not _table_exists(db, "telephony_dial_targets"):
        return
    db.execute(text("DROP TABLE telephony_dial_targets"))
    db.commit()
