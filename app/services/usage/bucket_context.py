"""Canonical usage bucket context (JSONB) helpers."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from uuid import UUID

_NONE = "__none__"

# Stable keys stored in llm_usage_daily.context (extend without new columns).
# evaluation_row_id / call_import_row_id may appear on legacy rows only.
KNOWN_CONTEXT_KEYS = frozenset(
    {
        "resource_id",
        "resource_type",
        "call_import_id",
        "evaluation_id",
        "evaluation_row_id",
        "call_import_row_id",
        "credential_id",
        "agent_id",
        "job_id",
        "user_id",
        "trace_id",
    }
)

# Per-request identifiers — useful in LLMUsageContext.extra but must not
# create a new Redis/PG bucket per call.
_HIGH_CARDINALITY_EXTRA_KEYS = frozenset(
    {
        "evaluator_result_id",
        "result_short_id",
        "metric_studio_result_id",
        "conversation_id",
        "call_short_id",
    }
)

# Never store roll-up counters in JSONB — they stay as BIGINT columns for SUM().
_FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
        "reasoning_tokens",
        "audio_seconds",
        "tts_characters",
        "call_count",
        "total_tokens",
    }
)


def build_bucket_context(
    *,
    resource_id: Optional[UUID] = None,
    resource_type: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Build a normalized string-keyed context dict for rollup buckets."""
    ctx: Dict[str, str] = {}
    if resource_id is not None:
        ctx["resource_id"] = str(resource_id)
    if resource_type:
        ctx["resource_type"] = resource_type
    if extra:
        for key, value in extra.items():
            if value is None or key in ctx:
                continue
            if key in _FORBIDDEN_CONTEXT_KEYS or key in _HIGH_CARDINALITY_EXTRA_KEYS:
                continue
            ctx[key] = str(value)
    return ctx


def context_bucket_token(context: Optional[Dict[str, Any]]) -> str:
    """Stable Redis bucket token for a context dict."""
    if not context:
        return _NONE
    normalized = {k: str(v) for k, v in sorted(context.items()) if v is not None}
    if not normalized:
        return _NONE
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def parse_context_bucket_token(token: str) -> Dict[str, str]:
    if not token or token == _NONE:
        return {}
    try:
        parsed = json.loads(token)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items() if v is not None}


def legacy_resource_context(
    resource_id: Optional[UUID],
    resource_type: Optional[str],
) -> Dict[str, str]:
    return build_bucket_context(
        resource_id=resource_id,
        resource_type=resource_type,
    )


def resource_id_from_context(context: Optional[Dict[str, Any]]) -> Optional[UUID]:
    if not context:
        return None
    raw = context.get("resource_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def resource_type_from_context(context: Optional[Dict[str, Any]]) -> Optional[str]:
    if not context:
        return None
    raw = context.get("resource_type")
    return str(raw) if raw else None
