from app.services.classification_metric_scores import (
    classification_facets_from_entry,
    enrich_classification_metric_entry,
)


def test_classification_facets_from_answers():
    entry = {
        "type": "classification",
        "answers": {
            "noul": {"noul": 0.23, "type": "noul"},
            "choice": {"choice": "other", "confidence": 0.56},
            "score": {
                "score": 1.04,
                "legend": {"0": "Calm", "1": "Frustrated", "2": "Angry"},
                "probabilities": {"0": 0.04, "1": 0.88, "2": 0.08},
            },
        },
    }
    facets = classification_facets_from_entry(entry)
    assert facets["yes_no"] == "No"
    assert facets["choice"] == "other"
    assert facets["level"] == "Frustrated"


def test_enrich_classification_metric_entry_adds_flat_fields():
    entry = {
        "type": "classification",
        "answers": {
            "noul": {"noul": 0.8},
            "choice": {"choice": "Issue in the product"},
        },
    }
    enriched = enrich_classification_metric_entry(entry)
    assert enriched["classification_yes_no"] == "Yes"
    assert enriched["classification_choice"] == "Issue in the product"



def test_tied_probabilities_pick_smallest_key_regardless_of_order():
    a = classification_facets_from_entry({"answers": {"choice": {"probabilities": {"zeta": 0.5, "alpha": 0.5}}}})
    b = classification_facets_from_entry({"answers": {"choice": {"probabilities": {"alpha": 0.5, "zeta": 0.5}}}})
    assert a["choice"] == b["choice"] == "alpha"


def test_negative_probabilities_still_pick_a_winner():
    facets = classification_facets_from_entry({"answers": {"choice": {"probabilities": {"a": -3.0, "b": -2.0}}}})
    assert facets["choice"] == "b"


def test_non_numeric_level_key_with_legend_does_not_crash():
    facets = classification_facets_from_entry(
        {"answers": {"score": {"legend": {"0": "Calm"}, "probabilities": {"x": 0.9}}}}
    )
    assert facets["level"] == "x"
