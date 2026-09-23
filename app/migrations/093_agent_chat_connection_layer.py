"""Add Cekura-style chat connection + main/test LLM columns on agents."""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Agent chat connection layer (internal_llm main/test LLM config)"


def upgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE agents
                ADD COLUMN IF NOT EXISTS chat_connection_type VARCHAR(32),
                ADD COLUMN IF NOT EXISTS main_llm_provider VARCHAR(64),
                ADD COLUMN IF NOT EXISTS main_llm_model VARCHAR(255),
                ADD COLUMN IF NOT EXISTS main_llm_credential_id UUID,
                ADD COLUMN IF NOT EXISTS main_llm_config JSONB,
                ADD COLUMN IF NOT EXISTS test_llm_provider VARCHAR(64),
                ADD COLUMN IF NOT EXISTS test_llm_model VARCHAR(255),
                ADD COLUMN IF NOT EXISTS test_llm_credential_id UUID,
                ADD COLUMN IF NOT EXISTS test_llm_config JSONB
            """
        )
    )
    db.commit()


def downgrade(db: Session):
    db.execute(
        text(
            """
            ALTER TABLE agents
                DROP COLUMN IF EXISTS chat_connection_type,
                DROP COLUMN IF EXISTS main_llm_provider,
                DROP COLUMN IF EXISTS main_llm_model,
                DROP COLUMN IF EXISTS main_llm_credential_id,
                DROP COLUMN IF EXISTS main_llm_config,
                DROP COLUMN IF EXISTS test_llm_provider,
                DROP COLUMN IF EXISTS test_llm_model,
                DROP COLUMN IF EXISTS test_llm_credential_id,
                DROP COLUMN IF EXISTS test_llm_config
            """
        )
    )
    db.commit()
