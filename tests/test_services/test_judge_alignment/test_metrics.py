"""Unit tests for app.services.judge_alignment.metrics.

Covers the pure-function alignment metrics used to score an LLM judge
against human labels:

- confusion_matrix: TP / FP / TN / FN counts with the convention
  fail = 1 (positive class), pass = 0.
- precision / recall / f1_score / cohen_kappa: classic binary metrics
  with the project's own zero-division semantics (return 0 instead of
  raising).
- compute_alignment_metrics: the JSON blob persisted on JudgeRun.metrics
  that the UI renders.
- split_balanced: deterministic dev/test split that preserves class
  ratio and is reproducible given the same seed.

All functions in this module are pure; no DB or network access is
required.
"""

import math

from app.services.judge_alignment.metrics import (
    cohen_kappa,
    compute_alignment_metrics,
    confusion_matrix,
    f1_score,
    per_sample_classification,
    precision,
    recall,
    split_balanced,
)


# ---------------------------------------------------------------------------
# confusion_matrix
# ---------------------------------------------------------------------------


def test_confusion_matrix_perfect_agreement_counts_each_class_correctly():
    labels = ["fail", "fail", "pass", "pass", "pass"]
    preds = ["fail", "fail", "pass", "pass", "pass"]

    cm = confusion_matrix(labels, preds)

    assert cm == {"tp": 2, "fp": 0, "tn": 3, "fn": 0, "n": 5}


def test_confusion_matrix_drops_pairs_where_either_side_is_none():
    labels = ["fail", None, "pass", "fail"]
    preds = ["fail", "pass", None, "pass"]

    cm = confusion_matrix(labels, preds)

    # Only the first ("fail","fail") and the last ("fail","pass") survive.
    assert cm == {"tp": 1, "fp": 0, "tn": 0, "fn": 1, "n": 2}


def test_confusion_matrix_normalises_truthy_falsy_aliases():
    """The label normaliser should accept AlignEval / CSV-style aliases."""
    labels = ["1", "true", "positive", "0", "false", "negative"]
    preds = ["fail", "fail", "fail", "pass", "pass", "pass"]

    cm = confusion_matrix(labels, preds)

    assert cm == {"tp": 3, "fp": 0, "tn": 3, "fn": 0, "n": 6}


def test_confusion_matrix_returns_zero_n_on_empty_input():
    cm = confusion_matrix([], [])
    assert cm == {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "n": 0}


# ---------------------------------------------------------------------------
# precision / recall / f1
# ---------------------------------------------------------------------------


def test_precision_returns_zero_when_no_positive_predictions():
    """No predicted positives => precision is undefined; return 0, don't raise."""
    assert precision(tp=0, fp=0) == 0.0


def test_recall_returns_zero_when_no_positive_labels():
    assert recall(tp=0, fn=0) == 0.0


def test_f1_returns_zero_when_precision_and_recall_are_both_zero():
    assert f1_score(p=0.0, r=0.0) == 0.0


def test_f1_is_harmonic_mean_of_precision_and_recall():
    # Half of positives caught, half of flagged were correct -> P=R=0.5, F1=0.5.
    assert f1_score(p=0.5, r=0.5) == 0.5
    # Asymmetric case: P=1.0, R=0.5 -> F1 = 2*1*0.5/(1+0.5) ~ 0.6667.
    assert math.isclose(f1_score(p=1.0, r=0.5), 2 / 3, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# cohen_kappa
# ---------------------------------------------------------------------------


def test_cohen_kappa_returns_one_for_perfect_agreement():
    # 3 TP + 3 TN out of 6 -> po=1, pe<1 -> kappa=1.
    assert cohen_kappa(tp=3, fp=0, tn=3, fn=0) == 1.0


def test_cohen_kappa_returns_negative_for_complete_disagreement():
    # Judge inverts every label: 3 FP + 3 FN, no agreement at all.
    assert cohen_kappa(tp=0, fp=3, tn=0, fn=3) < 0


def test_cohen_kappa_returns_zero_when_only_chance_agreement():
    """When the judge always predicts the majority class, kappa ≈ 0."""
    # Labels: 7 fail / 3 pass. Judge always predicts "fail".
    # -> tp=7, fp=3, tn=0, fn=0.
    # po = 7/10 = 0.7
    # pe = 0.7*1.0 + 0.3*0.0 = 0.7
    # kappa = (po - pe) / (1 - pe) = 0.0
    assert math.isclose(cohen_kappa(tp=7, fp=3, tn=0, fn=0), 0.0, abs_tol=1e-9)


def test_cohen_kappa_returns_zero_when_n_is_zero():
    assert cohen_kappa(tp=0, fp=0, tn=0, fn=0) == 0.0


def test_cohen_kappa_handles_pe_equals_one_edge_case():
    """If pe == 1 (everyone predicts the same class) kappa is undefined.

    The implementation is documented to return 1.0 when observed
    agreement is also perfect, else 0.0.
    """
    # Both raters always predict "pass" -> pe = 1 and po = 1.
    assert cohen_kappa(tp=0, fp=0, tn=5, fn=0) == 1.0


# ---------------------------------------------------------------------------
# compute_alignment_metrics
# ---------------------------------------------------------------------------


def test_compute_alignment_metrics_perfect_agreement_blob():
    labels = ["fail", "pass", "fail", "pass"]
    preds = ["fail", "pass", "fail", "pass"]

    blob = compute_alignment_metrics(labels, preds)

    assert blob["precision"] == 1.0
    assert blob["recall"] == 1.0
    assert blob["f1"] == 1.0
    assert blob["kappa"] == 1.0
    assert blob["tp"] == 2
    assert blob["tn"] == 2
    assert blob["fp"] == 0
    assert blob["fn"] == 0
    assert blob["n"] == 4


def test_compute_alignment_metrics_returns_zero_metrics_for_empty_input():
    blob = compute_alignment_metrics([], [])
    assert blob == {
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "kappa": 0.0,
        "tp": 0,
        "fp": 0,
        "tn": 0,
        "fn": 0,
        "n": 0,
    }


def test_compute_alignment_metrics_drops_unparseable_predictions_from_n():
    labels = ["fail", "pass", "fail"]
    preds = ["fail", None, "garbage"]  # only the first pair is usable

    blob = compute_alignment_metrics(labels, preds)

    assert blob["n"] == 1
    assert blob["tp"] == 1


def test_compute_alignment_metrics_rounds_rates_to_four_decimals():
    """Metric blob is JSON-persisted; long floats hurt the UI."""
    # 3 fails, judge catches 2 -> recall = 2/3 = 0.6667 (4dp).
    labels = ["fail", "fail", "fail"]
    preds = ["fail", "fail", "pass"]

    blob = compute_alignment_metrics(labels, preds)

    assert blob["recall"] == 0.6667
    # Precision is 1.0 (no false positives), F1 = 2*1*0.6667/(1+0.6667) = 0.8.
    assert blob["precision"] == 1.0
    assert blob["f1"] == 0.8


# ---------------------------------------------------------------------------
# per_sample_classification
# ---------------------------------------------------------------------------


def test_per_sample_classification_returns_each_quadrant():
    assert per_sample_classification("fail", "fail") == "tp"
    assert per_sample_classification("pass", "fail") == "fp"
    assert per_sample_classification("pass", "pass") == "tn"
    assert per_sample_classification("fail", "pass") == "fn"


def test_per_sample_classification_returns_none_when_either_side_missing():
    assert per_sample_classification(None, "fail") is None
    assert per_sample_classification("fail", None) is None
    assert per_sample_classification(None, None) is None


# ---------------------------------------------------------------------------
# split_balanced
# ---------------------------------------------------------------------------


def test_split_balanced_drops_unlabeled_samples():
    ids = ["a", "b", "c", "d"]
    labels = ["fail", None, "pass", None]

    dev, test = split_balanced(ids, labels, dev_ratio=0.5, seed=1)

    # Two labeled samples => one in each split.
    combined = sorted(dev + test)
    assert combined == ["a", "c"]


def test_split_balanced_preserves_class_ratio():
    """50/50 split of a 6-fail / 4-pass dataset should keep ratio in each half."""
    ids = [f"id{i}" for i in range(10)]
    labels = ["fail"] * 6 + ["pass"] * 4

    dev, test = split_balanced(ids, labels, dev_ratio=0.5, seed=42)

    def count_fails(half):
        # Reconstruct the label for each id by index lookup.
        return sum(1 for sid in half if labels[ids.index(sid)] == "fail")

    assert count_fails(dev) == 3
    assert count_fails(test) == 3
    assert len(dev) == 5
    assert len(test) == 5


def test_split_balanced_is_deterministic_for_same_seed():
    ids = [f"id{i}" for i in range(20)]
    labels = (["fail"] * 10) + (["pass"] * 10)

    a_dev, a_test = split_balanced(ids, labels, seed=7)
    b_dev, b_test = split_balanced(ids, labels, seed=7)

    assert a_dev == b_dev
    assert a_test == b_test


def test_split_balanced_changes_when_seed_changes():
    ids = [f"id{i}" for i in range(20)]
    labels = (["fail"] * 10) + (["pass"] * 10)

    a_dev, _ = split_balanced(ids, labels, seed=1)
    b_dev, _ = split_balanced(ids, labels, seed=2)

    # Same multiset of ids (deterministic balance), but ordering or
    # which specific ids land in dev should differ for at least one seed
    # pair on a 20-sample dataset.
    assert a_dev != b_dev


def test_split_balanced_dev_ratio_one_puts_everything_in_dev():
    ids = ["a", "b", "c", "d"]
    labels = ["fail", "pass", "fail", "pass"]

    dev, test = split_balanced(ids, labels, dev_ratio=1.0, seed=0)

    assert sorted(dev) == sorted(ids)
    assert test == []


def test_split_balanced_dev_ratio_zero_puts_everything_in_test():
    ids = ["a", "b", "c", "d"]
    labels = ["fail", "pass", "fail", "pass"]

    dev, test = split_balanced(ids, labels, dev_ratio=0.0, seed=0)

    assert dev == []
    assert sorted(test) == sorted(ids)
