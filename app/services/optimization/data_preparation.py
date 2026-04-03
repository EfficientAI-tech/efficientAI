"""
Convert historical EvaluatorResult rows into the training data format
expected by GEPA's DefaultAdapter (``DefaultDataInst``).
"""

from typing import Any, Dict, List

from app.models.database import EvaluatorResult, Metric


def build_trainset(
    training_data: List[EvaluatorResult],
    metrics: List[Metric],
) -> List[Dict[str, Any]]:
    """
    Each EvaluatorResult becomes one GEPA training example:

    * ``input``  -- the conversation transcript (truncated to 3 000 chars)
    * ``additional_context`` -- historical metric scores keyed as
      ``metric_<name>``
    * ``answer`` -- a qualitative label derived from the average score
    """
    trainset: List[Dict[str, Any]] = []

    for result in training_data:
        if not result.transcription:
            continue

        metric_context: Dict[str, str] = {}
        if result.metric_scores:
            scores = result.metric_scores if isinstance(result.metric_scores, dict) else {}
            for m in metrics:
                if m.name in scores:
                    metric_context[f"metric_{m.name}"] = str(scores[m.name])

        answer = _label_from_scores(result.metric_scores)

        trainset.append({
            "input": result.transcription[:3000],
            "additional_context": metric_context,
            "answer": answer,
        })

    return trainset


def _label_from_scores(metric_scores: Any) -> str:
    """Derive a qualitative answer string from numeric metric scores."""
    if not metric_scores or not isinstance(metric_scores, dict):
        return "High quality conversation achieving all metric targets."

    numeric = [float(v) for v in metric_scores.values() if isinstance(v, (int, float))]
    if not numeric:
        return "High quality conversation achieving all metric targets."

    avg = sum(numeric) / len(numeric)
    if avg >= 0.8:
        return "Excellent: all metrics above threshold."
    if avg >= 0.5:
        return "Acceptable: some metrics need improvement."
    return "Poor: significant improvement needed."
