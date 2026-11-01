"""Diarisation cancel/render helpers (used by call-import API routes)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.models.database import CallImportRow

CANCELLED_BY_USER_ERROR: str = "Diarisation cancelled by user"


def _cancellable_diarisation_states() -> Tuple[str, ...]:
    """States that a diarisation row can be cancelled from."""
    return ("pending", "running")


def _revoke_diarisation_task(row: CallImportRow) -> None:
    """Best-effort revoke of a single row's diarisation Celery task."""
    task_id = (row.celery_task_id or "").strip()
    if not task_id:
        return
    try:
        from app.workers.celery_revoke import revoke_celery_tasks

        revoke_celery_tasks([task_id])
        logger.info(
            "Revoked diarisation task {} for call-import row {}",
            task_id,
            row.id,
        )
    except Exception as exc:  # noqa: BLE001 — revoke is best-effort
        logger.warning(
            "Failed to revoke diarisation task {} for row {}: {}",
            task_id,
            row.id,
            exc,
        )


def _apply_diarisation_cancel(rows: List[CallImportRow]) -> Tuple[int, int]:
    """Cancel diarisation on every cancellable row in ``rows``.

    Returns ``(cancelled, skipped)``. Caller owns ``db.commit()``.
    """
    cancellable_states = _cancellable_diarisation_states()
    cancelled = 0
    skipped = 0
    for row in rows:
        if (row.diarised_transcript_status or "").lower() not in cancellable_states:
            skipped += 1
            continue
        row.diarised_transcript_status = "failed"
        row.diarised_transcript_error = CANCELLED_BY_USER_ERROR
        _revoke_diarisation_task(row)
        row.celery_task_id = None
        cancelled += 1
    return cancelled, skipped


def _render_diarised_segments_text(
    segments: Optional[List[Dict[str, Any]]],
    *,
    swap: bool = False,
) -> str:
    """Render ``CallImportRow.diarised_segments`` as ``<speaker>: <text>`` lines."""
    if not segments:
        return ""
    out: List[str] = []
    for turn in segments:
        if not isinstance(turn, dict):
            continue
        speaker = (turn.get("speaker") or "").strip()
        text = (turn.get("text") or "").strip()
        if not speaker or not text:
            continue
        if swap:
            if speaker == "agent":
                speaker = "user"
            elif speaker == "user":
                speaker = "agent"
        out.append(f"{speaker}: {text}")
    return "\n".join(out)
