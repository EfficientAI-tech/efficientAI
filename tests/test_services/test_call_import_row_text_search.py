"""Unit tests for call-import row search helpers."""

from uuid import uuid4

from sqlalchemy.sql.elements import BooleanClauseList

from app.models.database import CallImportRow
from app.services.call_imports.row_text_search import (
    conversation_id_substring_filter,
    ilike_substring_pattern,
    normalize_row_search_term,
)


def test_normalize_row_search_term_strips_and_empty():
    assert normalize_row_search_term("  abc  ") == "abc"
    assert normalize_row_search_term("") is None
    assert normalize_row_search_term(None) is None
    assert normalize_row_search_term("%") is None
    assert normalize_row_search_term("___") is None


def test_ilike_substring_pattern_escapes_wildcards():
    assert ilike_substring_pattern("100%") == r"%100\%%"
    assert ilike_substring_pattern("a_b") == r"%a\_b%"


def test_conversation_id_substring_filter_matches_conversation_id():
    clause = conversation_id_substring_filter("alpha-01")
    assert clause is not None
    assert not isinstance(clause, BooleanClauseList)


def test_conversation_id_substring_filter_row_uuid_uses_or_clause():
    row_id = uuid4()
    clause = conversation_id_substring_filter(str(row_id))
    assert clause is not None
    assert isinstance(clause, BooleanClauseList)
