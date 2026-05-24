"""
Pure-function alignment metrics for binary LLM-judge calibration.

Mirrors the metrics AlignEval surfaces (precision / recall / F1 /
Cohen's kappa, plus the underlying confusion matrix). Implemented from
scratch so we don't take a sklearn dependency for ~30 lines of math.

Convention used throughout this module:

    "fail" == 1 (positive class, i.e. the defect we're trying to detect)
    "pass" == 0 (negative class)

This matches AlignEval's convention where label=1 means the LLM output
failed the criteria.

All inputs are aligned lists of equal length: index i pairs label[i]
with prediction[i]. Items where either side is None are dropped from
the calculation -- callers receive a count of how many were skipped via
the returned `n` field.
"""

import math
from typing import Dict, Iterable, List, Optional, Tuple

VALID_LABELS = {"pass", "fail"}


def _to_binary(value: Optional[str]) -> Optional[int]:
    """Normalise a label string to 0/1, returning None if unusable."""
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in {"fail", "1", "true", "positive", "defect"}:
        return 1
    if v in {"pass", "0", "false", "negative", "ok"}:
        return 0
    return None


def confusion_matrix(
    labels: Iterable[Optional[str]],
    predictions: Iterable[Optional[str]],
) -> Dict[str, int]:
    """Return TP / FP / TN / FN (with positive class = "fail") and `n`."""
    tp = fp = tn = fn = n = 0

    for label, pred in zip(labels, predictions):
        y = _to_binary(label)
        yhat = _to_binary(pred)
        if y is None or yhat is None:
            continue
        n += 1
        if y == 1 and yhat == 1:
            tp += 1
        elif y == 0 and yhat == 1:
            fp += 1
        elif y == 0 and yhat == 0:
            tn += 1
        else:  # y == 1 and yhat == 0
            fn += 1

    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "n": n}


def precision(tp: int, fp: int) -> float:
    denom = tp + fp
    return tp / denom if denom else 0.0


def recall(tp: int, fn: int) -> float:
    denom = tp + fn
    return tp / denom if denom else 0.0


def f1_score(p: float, r: float) -> float:
    denom = p + r
    return (2 * p * r / denom) if denom else 0.0


def cohen_kappa(tp: int, fp: int, tn: int, fn: int) -> float:
    """Cohen's kappa between two binary raters (human label vs LLM judge)."""
    n = tp + fp + tn + fn
    if n == 0:
        return 0.0

    po = (tp + tn) / n  # observed agreement

    # Marginal probabilities for each rater predicting "fail".
    p_label_fail = (tp + fn) / n
    p_pred_fail = (tp + fp) / n
    pe = (
        p_label_fail * p_pred_fail
        + (1 - p_label_fail) * (1 - p_pred_fail)
    )

    if math.isclose(pe, 1.0):
        # Perfect agreement by chance -- kappa is undefined; report
        # observed agreement as 1.0 if everyone agrees, else 0.0.
        return 1.0 if math.isclose(po, 1.0) else 0.0

    return (po - pe) / (1 - pe)


def compute_alignment_metrics(
    labels: Iterable[Optional[str]],
    predictions: Iterable[Optional[str]],
) -> Dict[str, float]:
    """
    Build the full metrics blob persisted on `JudgeRun.metrics`::

        {
            "precision": float, "recall": float, "f1": float,
            "kappa": float,
            "tp": int, "fp": int, "tn": int, "fn": int, "n": int,
        }

    Empty / fully-unlabeled inputs return zeros for the rate metrics
    while still exposing `n=0` so the UI can show "no labels yet".
    """
    cm = confusion_matrix(labels, predictions)
    p = precision(cm["tp"], cm["fp"])
    r = recall(cm["tp"], cm["fn"])
    return {
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f1_score(p, r), 4),
        "kappa": round(cohen_kappa(cm["tp"], cm["fp"], cm["tn"], cm["fn"]), 4),
        **cm,
    }


def per_sample_classification(
    label: Optional[str], prediction: Optional[str]
) -> Optional[str]:
    """Return one of "tp"/"fp"/"tn"/"fn"/None for UI row highlighting."""
    y = _to_binary(label)
    yhat = _to_binary(prediction)
    if y is None or yhat is None:
        return None
    if y == 1 and yhat == 1:
        return "tp"
    if y == 0 and yhat == 1:
        return "fp"
    if y == 0 and yhat == 0:
        return "tn"
    return "fn"


def split_balanced(
    sample_ids: List[str],
    labels: List[Optional[str]],
    *,
    dev_ratio: float = 0.5,
    seed: int = 42,
) -> Tuple[List[str], List[str]]:
    """
    Split labeled samples into balanced dev / test ID lists.

    Mirrors AlignEval's optimization mode: same proportion of pass/fail
    in both halves, seeded for reproducibility. Unlabeled samples are
    dropped (they can't contribute to F1).
    """
    import random

    rng = random.Random(seed)
    pass_ids: List[str] = []
    fail_ids: List[str] = []

    for sid, lbl in zip(sample_ids, labels):
        b = _to_binary(lbl)
        if b is None:
            continue
        (fail_ids if b == 1 else pass_ids).append(sid)

    rng.shuffle(pass_ids)
    rng.shuffle(fail_ids)

    p_cut = int(round(len(pass_ids) * dev_ratio))
    f_cut = int(round(len(fail_ids) * dev_ratio))

    dev = pass_ids[:p_cut] + fail_ids[:f_cut]
    test = pass_ids[p_cut:] + fail_ids[f_cut:]

    rng.shuffle(dev)
    rng.shuffle(test)
    return dev, test
