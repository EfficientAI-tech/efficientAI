"""Audio metrics evaluation using Parselmouth and qualitative voice services."""

import os
import tempfile
from typing import Any

from loguru import logger

from .score_utils import get_metric_type_value


PARSELMOUTH_METRIC_NAMES = {"pitch variance", "jitter", "shimmer", "hnr"}


def evaluate_audio_metrics(
    audio_s3_key: str,
    audio_metrics: list,
    result_id: str,
) -> dict[str, dict[str, Any]]:
    """
    Evaluate audio-dependent metrics by downloading audio and running analysis.

    Args:
        audio_s3_key: S3 key for the audio file
        audio_metrics: List of Metric objects to evaluate
        result_id: Result ID for logging

    Returns:
        Dictionary mapping metric ID to score info
    """
    from app.services.s3_service import s3_service
    from app.services.voice_quality_service import calculate_audio_metrics
    from app.services.qualitative_voice_service import qualitative_voice_service

    metric_scores: dict[str, dict[str, Any]] = {}

    logger.info(f"[EvaluatorResult {result_id}] Running audio analysis on {len(audio_metrics)} metrics")

    audio_bytes = s3_service.download_file_by_key(audio_s3_key)
    if not audio_bytes:
        logger.warning(f"[EvaluatorResult {result_id}] Could not download audio from S3")
        for m in audio_metrics:
            metric_scores[str(m.id)] = {
                "value": None,
                "type": get_metric_type_value(m),
                "metric_name": m.name,
                "error": "audio_download_failed",
            }
        return metric_scores

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
    os.close(tmp_fd)

    try:
        with open(tmp_path, "wb") as f:
            f.write(audio_bytes)

        audio_metric_names = [m.name for m in audio_metrics]
        parselmouth_names = [n for n in audio_metric_names if n.lower() in PARSELMOUTH_METRIC_NAMES]
        qualitative_names = [n for n in audio_metric_names if n not in parselmouth_names]

        raw_results: dict = {}

        if parselmouth_names:
            raw_results.update(calculate_audio_metrics(tmp_path, parselmouth_names, is_url=False))

        if qualitative_names:
            raw_results.update(
                qualitative_voice_service.calculate_metrics(tmp_path, qualitative_names, is_url=False)
            )

        for m in audio_metrics:
            metric_scores[str(m.id)] = {
                "value": raw_results.get(m.name),
                "type": get_metric_type_value(m),
                "metric_name": m.name,
            }

        logger.info(f"[EvaluatorResult {result_id}] Audio analysis complete: {list(raw_results.keys())}")

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return metric_scores


def handle_audio_evaluation_error(
    audio_metrics: list,
    error: Exception,
) -> dict[str, dict[str, Any]]:
    """Build error response for all audio metrics when evaluation fails."""
    metric_scores: dict[str, dict[str, Any]] = {}
    for m in audio_metrics:
        metric_scores[str(m.id)] = {
            "value": None,
            "type": get_metric_type_value(m),
            "metric_name": m.name,
            "error": str(error),
        }
    return metric_scores
