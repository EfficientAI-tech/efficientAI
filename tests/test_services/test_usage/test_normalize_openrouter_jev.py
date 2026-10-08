"""Usage normalization for OpenRouter System One (Jev) responses."""

from app.services.usage.normalize import normalize_llm_usage, usage_snapshot_is_billable


def test_normalize_llm_usage_reads_usage_from_mapping_response():
    body = {
        "model": "typesafe/jev-1.13",
        "answers": {},
        "usage": {"input_tokens": 1200, "output_tokens": 0},
    }
    snapshot = normalize_llm_usage(raw_response=body)
    assert snapshot.prompt_tokens == 1200
    assert snapshot.completion_tokens == 0
    assert usage_snapshot_is_billable(snapshot) is True
