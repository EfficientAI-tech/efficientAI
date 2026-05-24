"""
Migration: Add per-leg credential_id columns to voicebundles.

Voice bundles reference providers by string name (stt_provider,
llm_provider, tts_provider, s2s_provider). Now that an organization can
have multiple API keys for the same provider, a bundle needs an explicit
way to pin one credential row per leg. We add four nullable UUID columns
- a NULL value means "use the default credential for the chosen
provider" (back-compat). The target table varies between aiproviders and
integrations depending on the provider, so we deliberately do NOT add a
foreign key constraint - validation is handled in app code.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Add stt/llm/tts/s2s_credential_id columns to voicebundles"


_COLUMNS = (
    "stt_credential_id",
    "llm_credential_id",
    "tts_credential_id",
    "s2s_credential_id",
)


def _column_exists(db: Session, column_name: str) -> bool:
    result = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'voicebundles'
              AND column_name = :column_name
            """
        ),
        {"column_name": column_name},
    )
    return result.first() is not None


def upgrade(db: Session):
    for column in _COLUMNS:
        if _column_exists(db, column):
            print(f"voicebundles.{column} already exists, skipping...")
            continue
        db.execute(text(f"ALTER TABLE voicebundles ADD COLUMN {column} UUID"))
        print(f"Added voicebundles.{column}")

    db.commit()
    print("Successfully added per-leg credential_id columns to voicebundles")


def downgrade(db: Session):
    for column in _COLUMNS:
        if _column_exists(db, column):
            db.execute(text(f"ALTER TABLE voicebundles DROP COLUMN {column}"))
    db.commit()
