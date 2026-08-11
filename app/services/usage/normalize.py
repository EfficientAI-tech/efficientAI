"""Normalize LiteLLM / provider usage objects into UsageSnapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class UsageSnapshot:
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _usage_mapping(raw: Any) -> Mapping[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return raw
    if hasattr(raw, "model_dump"):
        try:
            return raw.model_dump()
        except Exception:
            pass
    if hasattr(raw, "__dict__"):
        return {
            key: value
            for key, value in vars(raw).items()
            if not key.startswith("_")
        }
    return {}


def _details_dict(usage: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    details = usage.get(key)
    if details is None:
        return {}
    if isinstance(details, Mapping):
        return details
    if hasattr(details, "model_dump"):
        try:
            return details.model_dump()
        except Exception:
            pass
    if hasattr(details, "__dict__"):
        return {
            k: v for k, v in vars(details).items() if not k.startswith("_")
        }
    return {}


def normalize_llm_usage(raw_response: Any = None, *, usage: Any = None) -> UsageSnapshot:
    """Extract token buckets from a LiteLLM response or raw usage object."""
    usage_obj = usage
    if usage_obj is None and raw_response is not None:
        usage_obj = getattr(raw_response, "usage", None)

    data = _usage_mapping(usage_obj)
    prompt_tokens = _as_int(data.get("prompt_tokens") or data.get("input_tokens"))
    completion_tokens = _as_int(
        data.get("completion_tokens") or data.get("output_tokens")
    )

    cache_read = _as_int(data.get("cache_read_input_tokens"))
    cache_creation = _as_int(data.get("cache_creation_input_tokens"))

    prompt_details = _details_dict(data, "prompt_tokens_details")
    if not cache_read:
        cache_read = _as_int(prompt_details.get("cached_tokens"))
    if not cache_creation:
        cache_creation = _as_int(
            prompt_details.get("cache_write_tokens")
            or prompt_details.get("cache_creation_tokens")
        )

    completion_details = _details_dict(data, "completion_tokens_details")
    reasoning_tokens = _as_int(completion_details.get("reasoning_tokens"))

    return UsageSnapshot(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
        reasoning_tokens=reasoning_tokens,
    )
