"""PostgreSQL helpers for classification metric row filters.

Each predicate computes a row's *effective* facet value with exactly the same
precedence as ``classification_facets_from_entry`` (which the aggregates count
with), so filtering by a category returns exactly the rows counted under it:

* flat field (``classification_choice`` / ``classification_level``) when it is
  a non-blank string, else
* the explicit answer (choice only), else
* the highest-probability key (ties -> smallest key, code-point order), mapped
  through the score legend for levels, else
* the score formatted to two decimals (levels only).
"""

from __future__ import annotations

from sqlalchemy import TextClause, text

# ``metric_scores`` is stored as PostgreSQL ``json`` (not ``jsonb``). Cast
# nested values to ``jsonb`` before ``jsonb_each`` / ``jsonb_typeof``.

# Same values ``_as_float`` accepts from JSON strings (finite decimals).
_NUMERIC_TEXT_RE = r"^\s*[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?\s*$"


def _numeric_jsonb(value_sql: str) -> str:
    return (
        f"(jsonb_typeof({value_sql}) = 'number' OR "
        f"(jsonb_typeof({value_sql}) = 'string' AND ({value_sql} #>> '{{}}') ~ '{_NUMERIC_TEXT_RE}'))"
    )


def _flat_string(field: str) -> str:
    """Non-blank trimmed flat facet field, or NULL (non-strings ignored)."""
    path = f"metric_scores -> :mid -> '{field}'"
    return (
        f"(CASE WHEN json_typeof({path}) = 'string' "
        f"THEN nullif(btrim({path} #>> '{{}}'), '') END)"
    )


def _top_probability_key(probabilities_path: str) -> str:
    """Raw key with the highest numeric probability (ties -> smallest key)."""
    obj = (
        f"(CASE WHEN jsonb_typeof(({probabilities_path})::jsonb) = 'object' "
        f"THEN ({probabilities_path})::jsonb ELSE '{{}}'::jsonb END)"
    )
    return (
        f"(SELECT e.key FROM jsonb_each({obj}) AS e(key, value) "
        f"WHERE {_numeric_jsonb('e.value')} "
        f"ORDER BY (e.value #>> '{{}}')::double precision DESC, e.key COLLATE \"C\" ASC "
        f"LIMIT 1)"
    )


def effective_choice_sql() -> str:
    explicit = "metric_scores -> :mid -> 'answers' -> 'choice' -> 'choice'"
    top = _top_probability_key("metric_scores -> :mid -> 'answers' -> 'choice' -> 'probabilities'")
    return (
        f"coalesce({_flat_string('classification_choice')}, "
        f"nullif(btrim({explicit} #>> '{{}}'), ''), "
        f"nullif(btrim({top}), ''))"
    )


def effective_level_sql() -> str:
    score = "metric_scores -> :mid -> 'answers' -> 'score'"
    legend = f"{score} -> 'legend'"
    top = _top_probability_key(f"{score} -> 'probabilities'")
    label_from_probabilities = (
        "(SELECT CASE "
        "WHEN t.label IS NOT NULL THEN nullif(btrim(t.label), '') "
        "ELSE nullif(btrim(t.k), '') END "
        f"FROM (SELECT s.k, coalesce({legend} ->> s.k, "
        f"CASE WHEN s.k ~ '^\\s*[-+]?[0-9]+\\s*$' THEN {legend} ->> ((s.k)::numeric)::text END) AS label "
        f"FROM (SELECT {top} AS k) s WHERE s.k IS NOT NULL) t)"
    )
    score_value = f"({score} -> 'score')::jsonb"
    score_fallback = (
        f"(CASE WHEN {_numeric_jsonb(score_value)} "
        f"THEN (round(({score_value} #>> '{{}}')::numeric, 2))::text END)"
    )
    return f"coalesce({_flat_string('classification_level')}, {label_from_probabilities}, {score_fallback})"


def classification_level_row_predicate(metric_id: str, level: str) -> TextClause:
    """SQL boolean: row's effective classification level matches ``level`` (case-insensitive)."""
    return text(f"lower({effective_level_sql()}) = :lvl").bindparams(
        mid=str(metric_id), lvl=level.strip().lower()
    )


def classification_choice_row_predicate(metric_id: str, choice: str) -> TextClause:
    """SQL boolean: row's effective classification choice matches ``choice`` (case-insensitive)."""
    return text(f"lower({effective_choice_sql()}) = :ch").bindparams(
        mid=str(metric_id), ch=choice.strip().lower()
    )
