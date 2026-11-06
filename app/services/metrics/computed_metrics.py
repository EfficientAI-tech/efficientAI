"""Registry of deterministic call-import metric scorers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from app.models.database import Metric
from app.models.enums import MetricScoringMethod, MetricType
from app.services.evaluation.transcript_error_rates import (
    compute_transcript_error_rates,
    select_comparison_texts,
)


@dataclass(frozen=True)
class ComputedMetricContext:
    production_transcript: str
    diarised_transcript: str
    diarised_segments: Optional[List[Dict[str, Any]]]
    diarised_speaker_swap: bool
    speaker_aliases: Optional[Mapping[str, Tuple[str, ...]]] = None
    diarised_native_transcript: str = ""


def _score_transcript_agreement(ctx: ComputedMetricContext) -> Dict[str, Any]:
    """Production user turns are the reference. Agent turns are ignored."""
    selected = select_comparison_texts(
        production_transcript=ctx.production_transcript,
        diarised_transcript=ctx.diarised_transcript,
        diarised_segments=ctx.diarised_segments,
        diarised_native_transcript=ctx.diarised_native_transcript,
        diarised_speaker_swap=ctx.diarised_speaker_swap,
        speaker_aliases=ctx.speaker_aliases,
    )
    rates = compute_transcript_error_rates(
        selected["reference"],
        selected["hypothesis"],
        mode=selected["mode"],
        script_mismatch=selected["script_mismatch"],
    )
    if rates.get("cer") is None or rates.get("wer") is None:
        return {"skipped": "production_user_empty"}
    return rates


def _chart_value(rate: float) -> float:
    return round(min(1.0, float(rate)), 4)


def _score_user_wer(metric: Metric, ctx: ComputedMetricContext) -> Dict[str, Any]:
    rates = _score_transcript_agreement(ctx)
    if "skipped" in rates:
        return rates
    return {
        "value": _chart_value(rates["wer"]),
        "type": MetricType.NUMBER.value,
        "metric_name": metric.name,
        "details": rates,
    }


def _score_user_cer(metric: Metric, ctx: ComputedMetricContext) -> Dict[str, Any]:
    rates = _score_transcript_agreement(ctx)
    if "skipped" in rates:
        return rates
    return {
        "value": _chart_value(rates["cer"]),
        "type": MetricType.NUMBER.value,
        "metric_name": metric.name,
        "details": rates,
    }


COMPUTED_TRANSCRIPT_SCORING_METHODS = frozenset(
    {
        MetricScoringMethod.USER_WER.value,
        MetricScoringMethod.USER_CER.value,
    }
)


def metric_scoring_method_key(metric: Metric) -> str:
    raw = getattr(metric, "scoring_method", None) or MetricScoringMethod.LLM.value
    return str(raw).strip().lower()


def metrics_require_transcript_agreement(metrics: Sequence[Metric]) -> bool:
    return any(
        metric_scoring_method_key(metric) in COMPUTED_TRANSCRIPT_SCORING_METHODS
        for metric in metrics
    )


COMPUTED_SCORERS: Dict[str, Callable[[Metric, ComputedMetricContext], Dict[str, Any]]] = {
    MetricScoringMethod.USER_WER.value: _score_user_wer,
    MetricScoringMethod.USER_CER.value: _score_user_cer,
}


def is_computed_metric(metric: Metric) -> bool:
    return metric_scoring_method_key(metric) in COMPUTED_SCORERS


def run_computed_scorer(
    metric: Metric,
    ctx: ComputedMetricContext,
) -> Dict[str, Any]:
    key = metric_scoring_method_key(metric)
    scorer = COMPUTED_SCORERS.get(key)
    if not scorer:
        return {"skipped": "unknown_computed_scorer"}
    result = scorer(metric, ctx)
    if "skipped" in result:
        return result
    return result
