"""Usage cost presentation helpers for API responses."""

from __future__ import annotations

from typing import Any, Dict, Optional

MICRO_USD_PER_DOLLAR = 1_000_000


def micro_to_usd(micro: int) -> float:
    return micro / MICRO_USD_PER_DOLLAR


def costs_from_micro(
    *,
    input_cost_micro_usd: int = 0,
    output_cost_micro_usd: int = 0,
    cache_read_cost_micro_usd: int = 0,
    cache_creation_cost_micro_usd: int = 0,
    reasoning_cost_micro_usd: int = 0,
    audio_cost_micro_usd: int = 0,
    tts_cost_micro_usd: int = 0,
    total_cost_micro_usd: Optional[int] = None,
    has_unpriced_usage: bool = False,
    currency: str = "USD",
) -> Dict[str, Any]:
    total_micro = (
        total_cost_micro_usd
        if total_cost_micro_usd is not None
        else (
            input_cost_micro_usd
            + output_cost_micro_usd
            + cache_read_cost_micro_usd
            + cache_creation_cost_micro_usd
            + reasoning_cost_micro_usd
            + audio_cost_micro_usd
            + tts_cost_micro_usd
        )
    )
    return {
        "input_cost_usd": micro_to_usd(input_cost_micro_usd),
        "output_cost_usd": micro_to_usd(output_cost_micro_usd),
        "cache_read_cost_usd": micro_to_usd(cache_read_cost_micro_usd),
        "cache_write_cost_usd": micro_to_usd(cache_creation_cost_micro_usd),
        "reasoning_cost_usd": micro_to_usd(reasoning_cost_micro_usd),
        "audio_cost_usd": micro_to_usd(audio_cost_micro_usd),
        "tts_cost_usd": micro_to_usd(tts_cost_micro_usd),
        "total_cost_usd": micro_to_usd(total_micro),
        "currency": currency,
        "has_unpriced_usage": has_unpriced_usage,
    }
