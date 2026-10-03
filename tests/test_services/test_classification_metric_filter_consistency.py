"""Classification row filters must select exactly the rows the aggregates count
under each category (PR review P1: "Choice filter returns extra rows")."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.services.classification_metric_scores import classification_facets_from_entry
from app.services.classification_metric_sql import (
    classification_choice_row_predicate,
    classification_level_row_predicate,
)

MID = "m1"

ENTRIES = {
    # explicit choice differs from the highest-probability key (the reported bug)
    1: {"answers": {"choice": {"choice": "billing", "probabilities": {"billing": 0.2, "refund": 0.8}}}},
    # flat field wins over everything
    2: {"classification_choice": "Refund", "answers": {"choice": {"choice": "billing"}}},
    # blank flat field and blank explicit choice fall through to probabilities
    3: {"classification_choice": "  ", "answers": {"choice": {"choice": " ", "probabilities": {"other": 0.6, "billing": 0.4}}}},
    # tie: smallest key wins, exactly one category
    4: {"answers": {"choice": {"probabilities": {"zeta": 0.5, "alpha": 0.5}}}},
    # non-numeric probability is skipped, numeric strings count
    5: {"answers": {"choice": {"probabilities": {"broken": "n/a", "refund": "0.7", "billing": 0.3}}}},
    # whitespace around labels is trimmed
    6: {"answers": {"choice": {"choice": " Billing "}}},
    # levels: flat, legend-mapped, raw key without legend entry, score fallback
    7: {"classification_level": "Angry", "answers": {"score": {"probabilities": {"0": 0.9}, "legend": {"0": "Calm"}}}},
    8: {"answers": {"score": {"legend": {"0": "Calm", "1": "Frustrated"}, "probabilities": {"0": 0.1, "1": 0.9}}}},
    9: {"answers": {"score": {"legend": {"0": "Calm"}, "probabilities": {"x": 0.9}}}},
    10: {"answers": {"score": {"score": 1.5}}},
    11: {"answers": {"score": {"score": 2, "probabilities": {}}}},
    # nothing usable
    12: {"answers": {"choice": {"probabilities": "not-an-object"}, "score": {"probabilities": [1, 2]}}},
}


@pytest.fixture
def scores_table(db_session):
    if db_session.get_bind().dialect.name != "postgresql":
        pytest.skip("classification row filters are PostgreSQL SQL (set TEST_DATABASE_URL)")
    db_session.execute(text("CREATE TEMP TABLE clf_rows (id int PRIMARY KEY, metric_scores json)"))
    for row_id, entry in ENTRIES.items():
        db_session.execute(
            text("INSERT INTO clf_rows (id, metric_scores) VALUES (:id, CAST(:scores AS json))"),
            {"id": row_id, "scores": json.dumps({MID: entry})},
        )
    yield db_session
    db_session.execute(text("DROP TABLE IF EXISTS clf_rows"))


def _matching_ids(db, predicate) -> set[int]:
    sql = text(f"SELECT id FROM clf_rows WHERE {predicate.text}").bindparams(*predicate._bindparams.values())
    return {row[0] for row in db.execute(sql)}


@pytest.mark.parametrize("facet,predicate", [
    ("choice", classification_choice_row_predicate),
    ("level", classification_level_row_predicate),
])
def test_filter_selects_exactly_the_counted_rows(scores_table, facet, predicate):
    buckets: dict[str, set[int]] = {}
    for row_id, entry in ENTRIES.items():
        value = classification_facets_from_entry(entry)[facet]
        if value:
            buckets.setdefault(value.lower(), set()).add(row_id)

    assert buckets, "fixture should produce categories"
    for label, counted in buckets.items():
        assert _matching_ids(scores_table, predicate(MID, label)) == counted, label


def test_reported_case_explicit_choice_beats_probabilities(scores_table):
    assert 1 in _matching_ids(scores_table, classification_choice_row_predicate(MID, "billing"))
    assert 1 not in _matching_ids(scores_table, classification_choice_row_predicate(MID, "refund"))


def test_tied_probabilities_pick_one_category(scores_table):
    assert 4 in _matching_ids(scores_table, classification_choice_row_predicate(MID, "alpha"))
    assert 4 not in _matching_ids(scores_table, classification_choice_row_predicate(MID, "zeta"))
