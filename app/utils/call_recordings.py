"""Shared helpers for call recording operations."""

import random

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.database import CallRecording


def generate_unique_call_short_id(db: Session, max_attempts: int = 100) -> str:
    """
    Generate a unique 6-digit short ID for a call recording.

    Args:
        db: Database session.
        max_attempts: Maximum attempts before failing.

    Returns:
        A unique 6-digit string ID.

    Raises:
        HTTPException: If a unique ID cannot be generated.
    """
    for _ in range(max_attempts):
        call_short_id = f"{random.randint(100000, 999999)}"
        existing = (
            db.query(CallRecording)
            .filter(CallRecording.call_short_id == call_short_id)
            .first()
        )
        if not existing:
            return call_short_id

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to generate unique call short ID",
    )

