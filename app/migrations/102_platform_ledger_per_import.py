"""Allow the same platform conversation on more than one import."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "platform ledger unique per import, not per workspace"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE platform_conversation_ledger
                DROP CONSTRAINT IF EXISTS uq_platform_ledger_workspace_provider_conversation
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE platform_conversation_ledger
                DROP CONSTRAINT IF EXISTS platform_conversation_ledger_workspace_id_provider_conversation_id_key
            """
        )
    )
    db.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_platform_ledger_import_conversation'
                ) THEN
                    ALTER TABLE platform_conversation_ledger
                        ADD CONSTRAINT uq_platform_ledger_import_conversation
                        UNIQUE (call_import_id, conversation_id);
                END IF;
            END $$
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE platform_conversation_ledger
                DROP CONSTRAINT IF EXISTS uq_platform_ledger_import_conversation
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE platform_conversation_ledger
                ADD CONSTRAINT uq_platform_ledger_workspace_provider_conversation
                UNIQUE (workspace_id, provider, conversation_id)
            """
        )
    )
    db.commit()
