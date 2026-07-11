"""
Migration: Per-credential Bifrost gateway auth header and secret overrides.

Allows each AI Provider to specify a custom auth header name, an environment
variable name for the secret, or an encrypted inline gateway auth secret.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = (
    "Add gateway_auth_header, gateway_auth_secret_env, and gateway_auth_secret "
    "on aiproviders for per-credential Bifrost authentication."
)


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
    if not _column_exists(db, "aiproviders", "gateway_auth_header"):
        db.execute(
            text(
                """
                ALTER TABLE aiproviders
                ADD COLUMN gateway_auth_header VARCHAR(64) NULL
                """
            )
        )
        print("Added aiproviders.gateway_auth_header (varchar, nullable)")

    if not _column_exists(db, "aiproviders", "gateway_auth_secret_env"):
        db.execute(
            text(
                """
                ALTER TABLE aiproviders
                ADD COLUMN gateway_auth_secret_env VARCHAR(128) NULL
                """
            )
        )
        print("Added aiproviders.gateway_auth_secret_env (varchar, nullable)")

    if not _column_exists(db, "aiproviders", "gateway_auth_secret"):
        db.execute(
            text(
                """
                ALTER TABLE aiproviders
                ADD COLUMN gateway_auth_secret VARCHAR NULL
                """
            )
        )
        print("Added aiproviders.gateway_auth_secret (varchar, nullable, encrypted at rest)")


def downgrade(db: Session):
    if _column_exists(db, "aiproviders", "gateway_auth_secret"):
        db.execute(text("ALTER TABLE aiproviders DROP COLUMN gateway_auth_secret"))
        print("Dropped aiproviders.gateway_auth_secret")

    if _column_exists(db, "aiproviders", "gateway_auth_secret_env"):
        db.execute(text("ALTER TABLE aiproviders DROP COLUMN gateway_auth_secret_env"))
        print("Dropped aiproviders.gateway_auth_secret_env")

    if _column_exists(db, "aiproviders", "gateway_auth_header"):
        db.execute(text("ALTER TABLE aiproviders DROP COLUMN gateway_auth_header"))
        print("Dropped aiproviders.gateway_auth_header")
