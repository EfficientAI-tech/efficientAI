"""PostgreSQL helpers for classification metric row filters."""

from __future__ import annotations

from sqlalchemy import TextClause, text

# ``metric_scores`` is stored as PostgreSQL ``json`` (not ``jsonb``). Cast
# nested objects to ``jsonb`` before ``jsonb_each`` / ``coalesce`` with literals.

_PROBABILITIES_JSONB = (
    "(metric_scores -> :mid -> 'answers' -> 'score' -> 'probabilities')::jsonb"
)


def classification_level_row_predicate(metric_id: str, level: str) -> TextClause:
    """SQL boolean: row's classification level matches ``level`` (case-insensitive).

    Matches ``classification_level`` when present, otherwise the legend label
    for the highest-probability key under ``answers.score.probabilities``.
    """
    mid = str(metric_id)
    lvl = level.strip().lower()
    return text(
        f"""
        (
            lower(coalesce(metric_scores -> :mid ->> 'classification_level', '')) = :lvl
            OR EXISTS (
                SELECT 1
                FROM (
                    SELECT
                        e.key AS win_key,
                        (e.value #>> '{{}}')::double precision AS prob
                    FROM jsonb_each(
                        coalesce({_PROBABILITIES_JSONB}, '{{}}'::jsonb)
                    ) AS e(key, value)
                ) probs
                WHERE probs.prob = (
                    SELECT MAX((e2.value #>> '{{}}')::double precision)
                    FROM jsonb_each(
                        coalesce({_PROBABILITIES_JSONB}, '{{}}'::jsonb)
                    ) AS e2(key, value)
                )
                AND lower(
                    coalesce(
                        metric_scores -> :mid -> 'answers' -> 'score' -> 'legend' ->> probs.win_key,
                        metric_scores -> :mid -> 'legend' ->> probs.win_key,
                        probs.win_key
                    )
                ) = :lvl
            )
        )
        """
    ).bindparams(mid=mid, lvl=lvl)


_CHOICE_PROBABILITIES_JSONB = (
    "(metric_scores -> :mid -> 'answers' -> 'choice' -> 'probabilities')::jsonb"
)


def classification_choice_row_predicate(metric_id: str, choice: str) -> TextClause:
    """SQL boolean: row's classification choice matches ``choice`` (case-insensitive).

    Matches ``classification_choice`` when present, explicit ``answers.choice.choice``,
    otherwise the highest-probability key under ``answers.choice.probabilities``.
    """
    mid = str(metric_id)
    ch = choice.strip().lower()
    return text(
        f"""
        (
            lower(coalesce(metric_scores -> :mid ->> 'classification_choice', '')) = :ch
            OR lower(
                coalesce(
                    metric_scores -> :mid -> 'answers' -> 'choice' ->> 'choice',
                    ''
                )
            ) = :ch
            OR EXISTS (
                SELECT 1
                FROM (
                    SELECT
                        e.key AS win_key,
                        (e.value #>> '{{}}')::double precision AS prob
                    FROM jsonb_each(
                        coalesce({_CHOICE_PROBABILITIES_JSONB}, '{{}}'::jsonb)
                    ) AS e(key, value)
                ) probs
                WHERE probs.prob = (
                    SELECT MAX((e2.value #>> '{{}}')::double precision)
                    FROM jsonb_each(
                        coalesce({_CHOICE_PROBABILITIES_JSONB}, '{{}}'::jsonb)
                    ) AS e2(key, value)
                )
                AND lower(coalesce(probs.win_key, '')) = :ch
            )
        )
        """
    ).bindparams(mid=mid, ch=ch)
