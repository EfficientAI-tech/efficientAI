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
