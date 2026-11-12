"""Normalize import row selection filters for bulk APIs."""

from __future__ import annotations

from typing import Optional, Tuple

from app.models.schemas import CallImportRowSelectionFilter


def normalize_row_selection_filter(
    row_filter: Optional[CallImportRowSelectionFilter],
) -> Tuple[str, Optional[str]]:
    if row_filter is None:
        return "", None
    q = (row_filter.q or "").strip()
    diarised = (row_filter.diarised_status or "").strip() or None
    return q, diarised
