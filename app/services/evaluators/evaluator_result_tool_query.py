"""Filter evaluator results by production tool calls stored in call_data."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Query
from sqlalchemy import text

_TOOL_ARRAY_EXISTS = text(
    """
    EXISTS (
        SELECT 1
        FROM jsonb_array_elements(
            CASE
                WHEN jsonb_typeof((evaluator_results.call_data::jsonb)->'tool_calls') = 'array'
                THEN (evaluator_results.call_data::jsonb)->'tool_calls'
                ELSE '[]'::jsonb
            END
            || CASE
                WHEN jsonb_typeof((evaluator_results.call_data::jsonb)->'knowledge_base_tool_calls') = 'array'
                THEN (evaluator_results.call_data::jsonb)->'knowledge_base_tool_calls'
                ELSE '[]'::jsonb
            END
        ) AS elem
        WHERE (elem->>'side' IS NULL OR elem->>'side' = 'production')
        AND (:tool_use IS NULL OR elem->>'tool' = :tool_use)
        AND (
            :tool_product IS NULL
            OR COALESCE(NULLIF(TRIM(elem->>'provider'), ''), 'unknown') = :tool_product
        )
        AND (NOT :failures_only OR elem->>'status' = 'error')
    )
    """
)


def apply_tool_call_filters(
    query: Query,
    *,
    tool_use: Optional[str] = None,
    tool_product: Optional[str] = None,
    failures_only: bool = False,
    has_tool_calls: bool = False,
) -> Query:
    tool_key = (tool_use or "").strip() or None
    product_key = (tool_product or "").strip() or None
    if tool_key is None and product_key is None and not failures_only and not has_tool_calls:
        return query
    clause = _TOOL_ARRAY_EXISTS.bindparams(
        tool_use=tool_key,
        tool_product=product_key,
        failures_only=bool(failures_only),
    )
    return query.filter(clause)