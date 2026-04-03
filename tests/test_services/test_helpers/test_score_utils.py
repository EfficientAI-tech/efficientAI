"""Unit tests for score utility helpers."""

from types import SimpleNamespace

from app.models.enums import MetricType, ModelProvider
from app.workers.tasks.helpers.score_utils import (
    extract_score,
    find_matching_key,
    get_metric_type_value,
    normalize_score,
    provider_matches,
)


def test_provider_matches_supports_string_and_enum():
    assert provider_matches("openai", ModelProvider.OPENAI) is True
    assert provider_matches(ModelProvider.OPENAI, ModelProvider.OPENAI) is True
    assert provider_matches(None, ModelProvider.OPENAI) is False
    assert provider_matches("anthropic", ModelProvider.OPENAI) is False


def test_extract_score_handles_common_payload_shapes():
    assert extract_score(4.2) == 4.2
    assert extract_score(True) is True
    assert extract_score({"score": 0.9}) == 0.9
    assert extract_score({"value": 3}) == 3
    assert extract_score({"rating": 7}) == 7
    assert extract_score("0.75") == 0.75
    assert extract_score("yes") is True
    assert extract_score("no") is False
    assert extract_score("not-a-number") is None


def test_find_matching_key_prefers_exact_then_fuzzy():
    keys = ["wer_score", "latency_ms", "quality rating"]

    assert find_matching_key("wer-score", keys) == "wer_score"
    assert find_matching_key("latency", keys) == "latency_ms"
    assert find_matching_key("quality_rating", keys) == "quality rating"
    assert find_matching_key("totally_unknown", keys) is None


def test_get_metric_type_value_handles_enum_or_string():
    metric_enum = SimpleNamespace(metric_type=MetricType.RATING)
    metric_string = SimpleNamespace(metric_type="BOOLEAN")

    assert get_metric_type_value(metric_enum) == "rating"
    assert get_metric_type_value(metric_string) == "boolean"


def test_normalize_score_for_rating_boolean_and_number():
    assert normalize_score(8, "rating") == 0.8
    assert normalize_score(0.2, "rating") == 0.2
    assert normalize_score(True, "boolean") is True
    assert normalize_score(0.7, "boolean") is True
    assert normalize_score(0.4, "boolean") is False
    assert normalize_score("hello", "boolean") is True
    assert normalize_score("5.5", "number") == 5.5
    assert normalize_score("abc", "number") is None
