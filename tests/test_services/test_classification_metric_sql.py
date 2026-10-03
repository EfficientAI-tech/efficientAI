"""SQL predicate helpers for classification metric drilldown filters."""

from app.services.classification_metric_sql import classification_choice_row_predicate


def test_classification_choice_predicate_includes_probability_path():
    clause = classification_choice_row_predicate("mid-123", "Billing")
    sql = str(clause)
    assert "classification_choice" in sql
    assert "answers" in sql and "choice" in sql
    assert "probabilities" in sql
    assert clause.compile().params["ch"] == "billing"
    assert clause.compile().params["mid"] == "mid-123"
