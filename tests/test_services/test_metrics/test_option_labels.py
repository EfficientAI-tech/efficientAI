from app.services.metrics.option_labels import (
    canonical_enum_option,
    enum_numeric_matches_ambiguous,
    classification_choice_labels_from_config,
    classification_score_labels_from_config,
    coerce_custom_config_for_storage,
    custom_config_for_api,
    enum_labels_equal,
    enum_option_labels_from_config,
)


def test_enum_option_labels_from_object_options():
    cfg = {"options": [{"value": "a", "description": "Alpha"}, "b"]}
    assert enum_option_labels_from_config(cfg) == ["a", "b"]


def test_enum_option_labels_from_numeric_scalars():
    cfg = {"options": [1, 2, 3]}
    assert enum_option_labels_from_config(cfg) == ["1", "2", "3"]


def test_enum_option_labels_from_object_with_numeric_value():
    cfg = {"options": [{"value": 5, "description": "Excellent"}]}
    assert enum_option_labels_from_config(cfg) == ["5"]


def test_classification_score_labels_from_object_criteria():
    cfg = {"score": {"criteria": [{"value": "high", "description": "Great"}, "low"]}}
    assert classification_score_labels_from_config(cfg) == ["high", "low"]


def test_coerce_custom_config_for_storage_matches_api_rules():
    raw = {"options": [{"value": "x", "description": "X"}, 2]}
    out = coerce_custom_config_for_storage("enum", raw)
    assert out["options"] == ["x", "2"]


def test_enum_option_labels_dedupe_and_float_whole_numbers():
    cfg = {"options": [1.0, 1, {"value": "a"}, "a"]}
    assert enum_option_labels_from_config(cfg) == ["1", "a"]


def test_enum_labels_equal_is_strict():
    assert enum_labels_equal("2", "2")
    assert enum_labels_equal("Good", "good")
    assert not enum_labels_equal("1", "1.0")
    assert not enum_labels_equal("01", "1")


def test_canonical_enum_option_numeric_only_when_unambiguous():
    assert canonical_enum_option("1.0", ["1", "2", "3"]) == "1"
    assert canonical_enum_option("1", ["01", "1"]) == "1"
    assert canonical_enum_option("1.0", ["01", "1"]) is None
    assert enum_numeric_matches_ambiguous("1.0", ["01", "1"])


def test_classification_choice_from_list_criteria():
    cfg = {
        "choice": {
            "criteria": [
                {"value": "resolved", "description": "Issue fixed"},
                {"value": "escalated", "description": "Handed off"},
            ]
        }
    }
    assert classification_choice_labels_from_config(cfg) == ["resolved", "escalated"]
    out = custom_config_for_api("classification", cfg)
    assert list(out["choice"]["criteria"].keys()) == ["resolved", "escalated"]
