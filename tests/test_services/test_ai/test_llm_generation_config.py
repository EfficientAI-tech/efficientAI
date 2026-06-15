"""Tests for LLM generation config merge helpers."""

from app.services.ai.llm_generation_config import (
    build_litellm_kwargs,
    merge_llm_config,
    resolve_effective_llm_config,
)


def test_merge_llm_config_prefers_primary_over_legacy():
    merged = merge_llm_config(
        {"temperature": 0.2, "top_p": 0.9},
        legacy_temperature=0.7,
        legacy_max_tokens=500,
    )
    assert merged["temperature"] == 0.2
    assert merged["top_p"] == 0.9
    assert merged["max_tokens"] == 500


def test_merge_llm_config_fills_legacy_when_missing():
    merged = merge_llm_config(
        None,
        legacy_temperature=0.7,
        legacy_max_tokens=128,
    )
    assert merged == {"temperature": 0.7, "max_tokens": 128}


def test_resolve_effective_llm_config_override_wins():
    effective = resolve_effective_llm_config(
        llm_config={"temperature": 0.5},
        override_llm_config={"top_p": 0.8},
        task_defaults={"temperature": 0.3},
    )
    assert effective["temperature"] == 0.5
    assert effective["top_p"] == 0.8


def test_build_litellm_kwargs_splits_extra_config():
    kwargs = build_litellm_kwargs(
        llm_config={"temperature": 0.4, "top_k": 40},
        task_defaults={"temperature": 0.3, "max_tokens": 1000},
    )
    assert kwargs["temperature"] == 0.4
    assert kwargs["max_tokens"] == 1000
    assert kwargs["config"] == {"top_k": 40}


def test_build_litellm_kwargs_metric_override_inheritance():
    kwargs = build_litellm_kwargs(
        llm_config={"temperature": 0.5},
        override_llm_config={"top_p": 0.95},
        task_defaults={"temperature": 0.3},
    )
    assert kwargs["temperature"] == 0.5
    assert kwargs["config"] == {"top_p": 0.95}
