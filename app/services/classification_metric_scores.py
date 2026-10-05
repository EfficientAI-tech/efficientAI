"""Extract filterable facets from Jev classification ``metric_scores`` entries."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        out = float(value)
        if out != out:  # NaN
            return None
        return out
    except (TypeError, ValueError):
        return None


def _top_probability_label(
    probabilities: Any,
    legend: Any,
) -> Optional[str]:
    if not isinstance(probabilities, dict) or not probabilities:
        return None
    # Ties go to the smallest key (code-point order) so the SQL row filters in
    # classification_metric_sql.py can reproduce the winner from jsonb, which
    # does not preserve insertion order.
    best_key: Optional[str] = None
    best_prob: Optional[float] = None
    for key, raw in probabilities.items():
        prob = _as_float(raw)
        if prob is None:
            continue
        key = str(key)
        if best_prob is None or prob > best_prob or (prob == best_prob and key < best_key):
            best_prob = prob
            best_key = key
    if best_key is None:
        return None
    if isinstance(legend, dict):
        legend_label = legend.get(best_key)
        if legend_label is None:
            try:
                legend_label = legend.get(str(int(best_key)))
            except ValueError:
                legend_label = None
        if legend_label is not None:
            return str(legend_label).strip() or None
    return best_key.strip() or None


def classification_facets_from_entry(entry: dict[str, Any]) -> Dict[str, Optional[str]]:
    """Return ``yes_no``, ``choice``, and ``level`` strings for filtering/display."""
    out: Dict[str, Optional[str]] = {
        "yes_no": None,
        "choice": None,
        "level": None,
    }
    if not isinstance(entry, dict):
        return out

    if entry.get("classification_yes_no") in ("Yes", "No"):
        out["yes_no"] = str(entry["classification_yes_no"])
    if isinstance(entry.get("classification_choice"), str):
        text = entry["classification_choice"].strip()
        if text:
            out["choice"] = text
    if isinstance(entry.get("classification_level"), str):
        text = entry["classification_level"].strip()
        if text:
            out["level"] = text

    answers = entry.get("answers")
    if not isinstance(answers, dict):
        return out

    noul = answers.get("noul")
    if out["yes_no"] is None and isinstance(noul, dict):
        p = _as_float(noul.get("noul"))
        if p is not None:
            out["yes_no"] = "Yes" if p >= 0.5 else "No"

    choice = answers.get("choice")
    if out["choice"] is None and isinstance(choice, dict):
        raw = choice.get("choice")
        if raw is not None and str(raw).strip():
            out["choice"] = str(raw).strip()
        else:
            top = _top_probability_label(choice.get("probabilities"), None)
            if top:
                out["choice"] = top

    score = answers.get("score")
    if out["level"] is None and isinstance(score, dict):
        legend = score.get("legend")
        top = _top_probability_label(score.get("probabilities"), legend)
        if top:
            out["level"] = top
        else:
            score_val = _as_float(score.get("score"))
            if score_val is not None:
                out["level"] = f"{score_val:.2f}"

    return out


def enrich_classification_metric_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Attach flat facet fields used for SQL filters and aggregates."""
    facets = classification_facets_from_entry(entry)
    if facets.get("yes_no"):
        entry["classification_yes_no"] = facets["yes_no"]
    if facets.get("choice"):
        entry["classification_choice"] = facets["choice"]
    if facets.get("level"):
        entry["classification_level"] = facets["level"]
    return entry


def classification_facet_match(
    entry: dict[str, Any],
    *,
    yes_no: Optional[str] = None,
    choice: Optional[str] = None,
    level: Optional[str] = None,
) -> bool:
    facets = classification_facets_from_entry(entry)
    if yes_no and (facets.get("yes_no") or "").lower() != yes_no.strip().lower():
        return False
    if choice and (facets.get("choice") or "").lower() != choice.strip().lower():
        return False
    if level and (facets.get("level") or "").lower() != level.strip().lower():
        return False
    return True
