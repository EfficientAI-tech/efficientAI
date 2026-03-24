"""
Migration: Remove duplicated speaker_segments for provider-linked evaluator results.

Provider integrations now keep transcript structure in call_data and derive
speaker segments on read, so persisting speaker_segments duplicates data.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

description = "Clear duplicated speaker_segments on provider-linked evaluator_results"


def upgrade(db: Session):
    result = db.execute(
        text(
            """
            UPDATE evaluator_results
            SET speaker_segments = NULL
            WHERE provider_platform IS NOT NULL
              AND speaker_segments IS NOT NULL
            """
        )
    )
    db.commit()
    print(f"Cleared speaker_segments for {result.rowcount or 0} provider-linked evaluator_results rows")


def downgrade(db: Session):
    # No safe automatic rollback: removed segments are derived dynamically from call_data.
    print("No-op downgrade for 014_cleanup_provider_evaluator_speaker_segments")
    db.commit()
