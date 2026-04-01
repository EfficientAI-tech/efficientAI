"""
Migration: Rename plivo_* tables to telephony_* for provider-agnostic telephony support.

Renames tables and key columns so the schema supports multiple telephony providers
(Plivo, Twilio, Vonage, etc.) rather than being Plivo-specific.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Rename plivo_* tables to telephony_*, add provider column, rename FK columns"


def _table_exists(db: Session, table_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
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
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = :column_name
            )
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


def upgrade(db: Session):
    """Rename plivo_* tables to telephony_* and add provider column."""

    # --- 1. Rename tables (order matters due to FK deps: children first) ---
    renames = [
        ("plivo_masked_sessions", "telephony_masked_sessions"),
        ("plivo_verify_sessions", "telephony_verify_sessions"),
        ("plivo_phone_numbers", "telephony_phone_numbers"),
        ("plivo_integrations", "telephony_integrations"),
    ]
    for old_name, new_name in renames:
        if _table_exists(db, old_name) and not _table_exists(db, new_name):
            db.execute(text(f"ALTER TABLE {old_name} RENAME TO {new_name}"))

    # --- 2. Add provider column to telephony_integrations ---
    if _table_exists(db, "telephony_integrations") and not _column_exists(db, "telephony_integrations", "provider"):
        db.execute(
            text("ALTER TABLE telephony_integrations ADD COLUMN provider VARCHAR(50) NOT NULL DEFAULT 'plivo'")
        )

    # --- 3. Rename columns ---
    # telephony_phone_numbers: plivo_integration_id -> telephony_integration_id
    if _table_exists(db, "telephony_phone_numbers") and _column_exists(db, "telephony_phone_numbers", "plivo_integration_id"):
        db.execute(
            text("ALTER TABLE telephony_phone_numbers RENAME COLUMN plivo_integration_id TO telephony_integration_id")
        )

    # telephony_phone_numbers: plivo_app_id -> provider_app_id
    if _table_exists(db, "telephony_phone_numbers") and _column_exists(db, "telephony_phone_numbers", "plivo_app_id"):
        db.execute(
            text("ALTER TABLE telephony_phone_numbers RENAME COLUMN plivo_app_id TO provider_app_id")
        )

    # telephony_verify_sessions: plivo_session_uuid -> provider_session_uuid
    if _table_exists(db, "telephony_verify_sessions") and _column_exists(db, "telephony_verify_sessions", "plivo_session_uuid"):
        db.execute(
            text("ALTER TABLE telephony_verify_sessions RENAME COLUMN plivo_session_uuid TO provider_session_uuid")
        )

    # telephony_masked_sessions: plivo_integration_id -> telephony_integration_id
    if _table_exists(db, "telephony_masked_sessions") and _column_exists(db, "telephony_masked_sessions", "plivo_integration_id"):
        db.execute(
            text("ALTER TABLE telephony_masked_sessions RENAME COLUMN plivo_integration_id TO telephony_integration_id")
        )

    # --- 4. Rename constraints ---
    # Replace old unique constraint with new one that includes provider
    try:
        db.execute(text("ALTER TABLE telephony_integrations DROP CONSTRAINT IF EXISTS uq_plivo_integration_org"))
    except Exception:
        pass
    try:
        db.execute(
            text(
                """
                ALTER TABLE telephony_integrations
                ADD CONSTRAINT uq_telephony_integration_org_provider
                UNIQUE (organization_id, provider)
                """
            )
        )
    except Exception:
        pass

    try:
        db.execute(text("ALTER TABLE telephony_phone_numbers DROP CONSTRAINT IF EXISTS uq_plivo_number_org_phone"))
    except Exception:
        pass
    try:
        db.execute(
            text(
                """
                ALTER TABLE telephony_phone_numbers
                ADD CONSTRAINT uq_telephony_number_org_phone
                UNIQUE (organization_id, phone_number)
                """
            )
        )
    except Exception:
        pass

    db.commit()


def downgrade(db: Session):
    """Reverse the rename back to plivo_* tables."""

    renames = [
        ("telephony_integrations", "plivo_integrations"),
        ("telephony_phone_numbers", "plivo_phone_numbers"),
        ("telephony_verify_sessions", "plivo_verify_sessions"),
        ("telephony_masked_sessions", "plivo_masked_sessions"),
    ]

    # Drop provider column
    if _table_exists(db, "telephony_integrations") and _column_exists(db, "telephony_integrations", "provider"):
        db.execute(text("ALTER TABLE telephony_integrations DROP COLUMN provider"))

    # Rename columns back
    if _table_exists(db, "telephony_phone_numbers") and _column_exists(db, "telephony_phone_numbers", "telephony_integration_id"):
        db.execute(text("ALTER TABLE telephony_phone_numbers RENAME COLUMN telephony_integration_id TO plivo_integration_id"))

    if _table_exists(db, "telephony_phone_numbers") and _column_exists(db, "telephony_phone_numbers", "provider_app_id"):
        db.execute(text("ALTER TABLE telephony_phone_numbers RENAME COLUMN provider_app_id TO plivo_app_id"))

    if _table_exists(db, "telephony_verify_sessions") and _column_exists(db, "telephony_verify_sessions", "provider_session_uuid"):
        db.execute(text("ALTER TABLE telephony_verify_sessions RENAME COLUMN provider_session_uuid TO plivo_session_uuid"))

    if _table_exists(db, "telephony_masked_sessions") and _column_exists(db, "telephony_masked_sessions", "telephony_integration_id"):
        db.execute(text("ALTER TABLE telephony_masked_sessions RENAME COLUMN telephony_integration_id TO plivo_integration_id"))

    for old_name, new_name in renames:
        if _table_exists(db, old_name) and not _table_exists(db, new_name):
            db.execute(text(f"ALTER TABLE {old_name} RENAME TO {new_name}"))

    db.commit()
