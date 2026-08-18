from app.services.observability.provider_call_enrichment import (
    is_sparse_provider_call_data,
    looks_like_retell_call_data,
    resolve_observability_provider_platform,
)


def test_looks_like_retell_call_data():
    assert looks_like_retell_call_data({"call_id": "call_123", "transcript_object": [{"role": "user", "content": "hi"}]})
    assert not looks_like_retell_call_data({"id": "abc", "messages": [{"role": "user", "content": "hi"}]})


def test_is_sparse_retell_call_data_when_metrics_missing():
    payload = {
        "transcript_object": [{"role": "user", "content": "hello"}],
        "call_analysis": {"call_summary": "done"},
    }
    assert is_sparse_provider_call_data(payload, "retell") is True

    payload["call_cost"] = {"combined_cost": 0.01}
    payload["latency"] = {"e2e": {"p50": 900}}
    assert is_sparse_provider_call_data(payload, "retell") is False


def test_resolve_observability_provider_platform_from_call_shape():
    class _Recording:
        provider_platform = "external"
        call_data = {"call_id": "call_123", "transcript_object": [{"role": "agent", "content": "hi"}]}
        agent_id = None

    assert resolve_observability_provider_platform(_Recording(), _Recording.call_data) == "retell"
