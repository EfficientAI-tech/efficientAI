"""Unit tests for call-import row search helpers."""

from app.services.call_imports.row_text_search import (
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
