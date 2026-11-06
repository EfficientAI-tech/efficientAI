"""Substring search helpers for call-import rows (pg_trgm-backed on Postgres)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import or_

from app.models.database import CallImportRow


def normalize_row_search_term(raw: Optional[str]) -> Optional[str]:
    term = (raw or "").strip()
    if not term:
        return None
    stripped = term.replace("\\", "").replace("%", "").replace("_", "")
    if not stripped:
        return None
    return term


def _escape_ilike(term: str) -> str:
    return (
        term.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def ilike_substring_pattern(term: str) -> str:
    return f"%{_escape_ilike(term)}%"


def conversation_id_substring_filter(term: Optional[str]):
    needle = normalize_row_search_term(term)
    if not needle:
        return None
    pattern = ilike_substring_pattern(needle)
    return CallImportRow.conversation_id.ilike(pattern, escape="\\")


def evaluation_row_free_text_filter(term: Optional[str]):
    needle = normalize_row_search_term(term)
    if not needle:
        return None
    pattern = ilike_substring_pattern(needle)
    return or_(
        CallImportRow.conversation_id.ilike(pattern, escape="\\"),
        CallImportRow.transcript.ilike(pattern, escape="\\"),
        CallImportRow.diarised_transcript.ilike(pattern, escape="\\"),
    )


def apply_conversation_id_search(query, term: Optional[str]):
    clause = conversation_id_substring_filter(term)
    if clause is None:
        return query
    return query.filter(clause)


def apply_evaluation_row_search(query, term: Optional[str]):
    clause = evaluation_row_free_text_filter(term)
    if clause is None:
        return query
    return query.filter(clause)
