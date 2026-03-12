"""Utility functions for score extraction and key matching."""


def provider_matches(db_provider, target_enum) -> bool:
    """Compare provider field (could be string or enum) with target enum."""
    if db_provider is None:
        return False
    if isinstance(db_provider, str):
        return db_provider.lower() == target_enum.value.lower()
    if hasattr(db_provider, "value"):
        return db_provider.value.lower() == target_enum.value.lower()
    return db_provider == target_enum


def extract_score(value):
    """Extract numeric/boolean score from various response formats."""
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, dict):
        if "score" in value:
            return value["score"]
        if "value" in value:
            return value["value"]
        if "rating" in value:
            return value["rating"]
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            if value.lower() in ("true", "yes"):
                return True
            if value.lower() in ("false", "no"):
                return False
    return None


def find_matching_key(target_key: str, response_keys: list[str]) -> str | None:
    """Find a matching key in the response, with fuzzy matching."""
    target_lower = target_key.lower().replace(" ", "_").replace("-", "_")
    target_words = set(target_lower.replace("_", " ").split())

    for key in response_keys:
        if key.lower().replace(" ", "_").replace("-", "_") == target_lower:
            return key

    for key in response_keys:
        key_lower = key.lower().replace(" ", "_").replace("-", "_")
        if target_lower in key_lower or key_lower in target_lower:
            return key

    best_match = None
    best_overlap = 0
    for key in response_keys:
        key_words = set(key.lower().replace("_", " ").replace("-", " ").split())
        overlap = len(target_words & key_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = key

    if best_overlap >= 1:
        return best_match
    return None


def get_metric_type_value(metric) -> str:
    """Extract metric type as lowercase string."""
    m_type = metric.metric_type.value if hasattr(metric.metric_type, "value") else metric.metric_type
    return m_type.lower() if isinstance(m_type, str) else m_type


def normalize_score(score, metric_type: str):
    """Normalize and validate score based on metric type."""
    if score is None:
        return None

    if metric_type == "rating":
        try:
            score = float(score)
            if score > 1.0:
                score = score / 10.0
            return max(0.0, min(1.0, score))
        except (ValueError, TypeError):
            return None

    if metric_type == "boolean":
        if isinstance(score, bool):
            return score
        if isinstance(score, (int, float)):
            return score > 0.5 if score <= 1 else score > 5
        return bool(score)

    if metric_type == "number":
        try:
            return float(score)
        except (ValueError, TypeError):
            return None

    return score
