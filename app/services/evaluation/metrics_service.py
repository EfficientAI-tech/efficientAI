"""Service for calculating evaluation metrics."""

from typing import Dict, Any, Optional
import time
from app.core.exceptions import MetricsCalculationError


class MetricsService:
    """Service for calculating evaluation metrics."""

    @staticmethod
    def calculate_wer(reference: str, hypothesis: str) -> float:
        """
        Calculate Word Error Rate (WER).

        Args:
            reference: Reference text
            hypothesis: Hypothesis text (transcribed)

        Returns:
            WER as a float (0.0 to 1.0, where 0.0 is perfect)
        """
        if not reference:
            return 0.0 if not hypothesis else float("inf")

        ref_words = reference.lower().split()
        hyp_words = hypothesis.lower().split()

        if not ref_words:
            return 0.0 if not hyp_words else float("inf")

        from rapidfuzz.distance import Levenshtein

        return Levenshtein.distance(ref_words, hyp_words) / len(ref_words)

    @staticmethod
    def calculate_cer(reference: str, hypothesis: str) -> float:
        """
        Calculate Character Error Rate (CER).

        Args:
            reference: Reference text
            hypothesis: Hypothesis text (transcribed)

        Returns:
            CER as a float (0.0 to 1.0, where 0.0 is perfect)
        """
        if not reference:
            return 0.0 if not hypothesis else float("inf")

        ref_chars = list(reference.lower())
        hyp_chars = list(hypothesis.lower())

        if not ref_chars:
            return 0.0 if not hyp_chars else float("inf")

        from rapidfuzz.distance import Levenshtein

        return Levenshtein.distance(ref_chars, hyp_chars) / len(ref_chars)

    @staticmethod
    def calculate_latency(start_time: float, end_time: float) -> Dict[str, float]:
        """
        Calculate latency metrics.

        Args:
            start_time: Processing start time (Unix timestamp)
            end_time: Processing end time (Unix timestamp)

        Returns:
            Dictionary with latency metrics
        """
        processing_time = end_time - start_time
        return {
            "latency_ms": processing_time * 1000,
            "latency_s": processing_time,
        }

    @staticmethod
    def calculate_rtf(audio_duration: float, processing_time: float) -> float:
        """
        Calculate Real-Time Factor (RTF).

        Args:
            audio_duration: Duration of audio in seconds
            processing_time: Processing time in seconds

        Returns:
            RTF value (lower is better, 1.0 means real-time)
        """
        if audio_duration == 0:
            return float("inf")
        return processing_time / audio_duration

    def calculate_metrics(
        self,
        metrics_requested: list[str],
        reference_text: Optional[str] = None,
        hypothesis_text: Optional[str] = None,
        audio_duration: Optional[float] = None,
        processing_time: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calculate requested metrics.

        Args:
            metrics_requested: List of metric names to calculate
            reference_text: Reference text for WER/CER
            hypothesis_text: Hypothesis text (transcription)
            audio_duration: Audio duration in seconds
            processing_time: Processing time in seconds

        Returns:
            Dictionary with calculated metrics

        Raises:
            MetricsCalculationError: If metric calculation fails
        """
        results: Dict[str, Any] = {}

        try:
            for metric in metrics_requested:
                if metric == "wer":
                    if reference_text and hypothesis_text:
                        results["wer"] = self.calculate_wer(reference_text, hypothesis_text)
                    else:
                        results["wer"] = None

                elif metric == "cer":
                    if reference_text and hypothesis_text:
                        results["cer"] = self.calculate_cer(reference_text, hypothesis_text)
                    else:
                        results["cer"] = None

                elif metric == "latency":
                    if processing_time:
                        latency_metrics = self.calculate_latency(0, processing_time)
                        results.update(latency_metrics)
                    else:
                        results["latency_ms"] = None
                        results["latency_s"] = None

                elif metric == "rtf":
                    if audio_duration and processing_time:
                        results["rtf"] = self.calculate_rtf(audio_duration, processing_time)
                    else:
                        results["rtf"] = None

                elif metric == "quality_score":
                    # Placeholder for quality score
                    # This would typically involve more sophisticated analysis
                    results["quality_score"] = None

            return results

        except Exception as e:
            raise MetricsCalculationError(f"Failed to calculate metrics: {str(e)}")


# Singleton instance
metrics_service = MetricsService()
