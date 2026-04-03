"""Tests for optimization training-data preparation."""

from types import SimpleNamespace

from app.services.optimization.data_preparation import _label_from_scores, build_trainset


def test_label_from_scores_maps_ranges():
    assert _label_from_scores({"a": 0.9, "b": 0.8}).startswith("Excellent")
    assert _label_from_scores({"a": 0.6, "b": 0.5}).startswith("Acceptable")
    assert _label_from_scores({"a": 0.2}).startswith("Poor")
    assert _label_from_scores(None).startswith("High quality")


def test_build_trainset_transforms_results_into_gepa_examples():
    metrics = [SimpleNamespace(name="wer"), SimpleNamespace(name="latency")]
    training_data = [
        SimpleNamespace(
            transcription="hello world",
            metric_scores={"wer": 0.1, "latency": 0.8, "other": 1},
        ),
        SimpleNamespace(transcription=None, metric_scores={"wer": 0.2}),  # skipped
    ]

    trainset = build_trainset(training_data, metrics)

    assert len(trainset) == 1
    assert trainset[0]["input"] == "hello world"
    assert trainset[0]["additional_context"]["metric_wer"] == "0.1"
    assert trainset[0]["additional_context"]["metric_latency"] == "0.8"
    assert "answer" in trainset[0]
