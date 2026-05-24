"""
Per-organization Judge Alignment settings.

Backed by the JSON column `organizations.judge_alignment_settings`. We
keep the read path tolerant (missing keys -> defaults) so the UI can
ship before any org has touched the settings panel.
"""

from typing import Dict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.database import Organization

DEFAULT_MIN_LABELS_TO_EVALUATE = 20
DEFAULT_MIN_LABELS_TO_OPTIMIZE = 50

DEFAULTS: Dict[str, int] = {
    "min_labels_to_evaluate": DEFAULT_MIN_LABELS_TO_EVALUATE,
    "min_labels_to_optimize": DEFAULT_MIN_LABELS_TO_OPTIMIZE,
}


def get_org_settings(organization_id: UUID, db: Session) -> Dict[str, int]:
    """Return current settings, merged on top of system defaults."""
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    raw = (org.judge_alignment_settings or {}) if org else {}

    return {
        "min_labels_to_evaluate": int(
            raw.get("min_labels_to_evaluate", DEFAULT_MIN_LABELS_TO_EVALUATE)
        ),
        "min_labels_to_optimize": int(
            raw.get("min_labels_to_optimize", DEFAULT_MIN_LABELS_TO_OPTIMIZE)
        ),
    }


def set_org_settings(
    organization_id: UUID,
    db: Session,
    *,
    min_labels_to_evaluate: int,
    min_labels_to_optimize: int,
) -> Dict[str, int]:
    """Validate and persist new settings. Raises HTTPException(400) on bad input."""
    if min_labels_to_evaluate < 1:
        raise HTTPException(
            status_code=400,
            detail="min_labels_to_evaluate must be >= 1",
        )
    if min_labels_to_optimize < min_labels_to_evaluate:
        raise HTTPException(
            status_code=400,
            detail="min_labels_to_optimize must be >= min_labels_to_evaluate",
        )

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.judge_alignment_settings = {
        "min_labels_to_evaluate": int(min_labels_to_evaluate),
        "min_labels_to_optimize": int(min_labels_to_optimize),
    }
    db.commit()

    return get_org_settings(organization_id, db)
