"""Cluster LLM request shaping for reasoning models."""

from app.services.call_import_metric_clusters import (
    CLUSTER_THINKING_BUDGET_TOKENS,
    _cluster_llm_attempts,
    _reasoning_cluster_model,
)


def test_reasoning_cluster_model_detects_glm():
    assert _reasoning_cluster_model("glm-5p3")
    assert _reasoning_cluster_model("accounts/fireworks/models/glm-5p3")
    assert not _reasoning_cluster_model("gpt-4o-mini")


def test_cluster_llm_attempts_glm_caps_thinking_not_16k():
    attempts = _cluster_llm_attempts("glm-5p3", 8000)
    assert len(attempts) == 2
    assert attempts[0]["max_tokens"] == 4096
    assert attempts[1]["max_tokens"] == 8000
    assert all(a["max_tokens"] <= 8000 for a in attempts)
    assert attempts[0]["completion_extra"]["thinking"]["budget_tokens"] == (
        CLUSTER_THINKING_BUDGET_TOKENS
    )
    assert "reasoning_effort" not in attempts[0].get("llm_config", {})
    assert "reasoning_effort" not in attempts[0].get("completion_extra", {})


def test_cluster_llm_attempts_non_reasoning_can_retry_higher_budget():
    attempts = _cluster_llm_attempts("gpt-4o-mini", 8000)
    assert [a["max_tokens"] for a in attempts] == [8000, 16000]
