"""PDF report generation service for Voice Playground comparisons."""

from __future__ import annotations

import base64
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


class VoicePlaygroundReportService:
    """Build and render comprehensive Voice Playground benchmark reports."""
    DEFAULT_REPORT_OPTIONS: dict[str, Any] = {
        "show_runs": True,
        "min_runs_to_show": 100,
        "include_latency": True,
        "include_ttfb": True,
        "include_endpoint": True,
        "include_naturalness": True,
        "include_hallucination": True,
        "include_prosody": True,
        "include_arousal": True,
        "include_valence": True,
        "include_cer": True,
        "include_wer": True,
        "include_hallucination_examples": True,
        "hallucination_examples_limit": 5,
        "include_disclaimer_sections": True,
        "include_methodology_sections": False,
        "zone_threshold_overrides": {},
    }

    def __init__(self) -> None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._logo_data_uri = self._build_logo_data_uri()

    @staticmethod
    def _build_logo_data_uri() -> str | None:
        """Load frontend favicon and convert it to an embeddable data URI."""
        project_root = Path(__file__).parent.parent.parent.parent
        candidate_paths = [
            project_root / "frontend" / "public" / "favicon_dark.png",
            project_root / "frontend" / "public" / "favicon_light.png",
        ]

        for logo_path in candidate_paths:
            if logo_path.exists():
                try:
                    image_bytes = logo_path.read_bytes()
                    encoded = base64.b64encode(image_bytes).decode("ascii")
                    return f"data:image/png;base64,{encoded}"
                except Exception:
                    continue
        return None

    @staticmethod
    def _safe_mean(values: list[float | int | None]) -> float | None:
        cleaned = [float(v) for v in values if v is not None]
        if not cleaned:
            return None
        return float(mean(cleaned))

    @staticmethod
    def _pick_metric(metrics: dict[str, Any] | None, *keys: str) -> float | None:
        if not metrics:
            return None
        for key in keys:
            value = metrics.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _to_pct(value: float | None) -> str:
        if value is None:
            return "N/A"
        if value <= 1:
            return f"{value * 100:.1f}%"
        return f"{value:.1f}%"

    @staticmethod
    def _to_ms(value: float | None) -> str:
        return "N/A" if value is None else f"{value:.0f}ms"

    @staticmethod
    def _to_score(value: float | None, decimals: int = 2) -> str:
        return "N/A" if value is None else f"{value:.{decimals}f}"

    @staticmethod
    def _format_metric_value(value: float | None, kind: str) -> str:
        if value is None:
            return "N/A"
        if kind == "ms":
            return f"{value:.0f}ms"
        if kind == "pct":
            return f"{value * 100:.1f}%"
        return f"{value:.2f}"

    @staticmethod
    def _humanize_identifier(value: str | None) -> str:
        if not value:
            return "N/A"
        raw = str(value).strip()
        if not raw:
            return "N/A"

        exact_map = {
            "elevenlabs": "ElevenLabs",
            "openai": "OpenAI",
            "voicemaker": "VoiceMaker",
            "deepgram": "Deepgram",
            "cartesia": "Cartesia",
            "sarvam": "Sarvam",
            "murf": "Murf",
            "google": "Google",
        }
        mapped = exact_map.get(raw.lower())
        if mapped:
            return mapped

        token_map = {
            "tts": "TTS",
            "asr": "ASR",
            "mos": "MOS",
            "wer": "WER",
            "cer": "CER",
            "v1": "V1",
            "v2": "V2",
            "v3": "V3",
            "hd": "HD",
            "turbo": "Turbo",
            "gpt": "GPT",
        }
        tokens = [t for t in re.split(r"[_\-\s]+", raw) if t]
        if not tokens:
            return raw

        out: list[str] = []
        for token in tokens:
            low = token.lower()
            if low in token_map:
                out.append(token_map[low])
            elif len(token) <= 4 and token.isupper():
                out.append(token)
            elif token and token[0].isdigit():
                out.append(token.upper())
            else:
                out.append(token.capitalize())
        return " ".join(out)

    @staticmethod
    def _endpoint_type(avg_ttfb_ms: float | None, avg_latency_ms: float | None) -> str:
        """Infer endpoint mode from timing profile when explicit metadata is unavailable."""
        if avg_ttfb_ms is None or avg_latency_ms is None or avg_latency_ms <= 0:
            return "Unknown endpoint"
        ratio = avg_ttfb_ms / avg_latency_ms
        if ratio <= 0.65:
            return "Streaming (inferred)"
        return "Non-streaming (inferred)"

    @staticmethod
    def _to_bool(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    def _normalize_report_options(self, report_options: dict[str, Any] | None) -> dict[str, Any]:
        normalized = dict(self.DEFAULT_REPORT_OPTIONS)
        if not isinstance(report_options, dict):
            return normalized

        bool_keys = {
            "show_runs",
            "include_latency",
            "include_ttfb",
            "include_endpoint",
            "include_naturalness",
            "include_hallucination",
            "include_prosody",
            "include_arousal",
            "include_valence",
            "include_cer",
            "include_wer",
            "include_hallucination_examples",
            "include_disclaimer_sections",
            "include_methodology_sections",
        }
        for key in bool_keys:
            if key in report_options:
                normalized[key] = self._to_bool(report_options.get(key), bool(normalized[key]))

        try:
            normalized["min_runs_to_show"] = max(0, int(report_options.get("min_runs_to_show", normalized["min_runs_to_show"])))
        except (TypeError, ValueError):
            normalized["min_runs_to_show"] = int(self.DEFAULT_REPORT_OPTIONS["min_runs_to_show"])

        try:
            normalized["hallucination_examples_limit"] = max(
                0, min(50, int(report_options.get("hallucination_examples_limit", normalized["hallucination_examples_limit"])))
            )
        except (TypeError, ValueError):
            normalized["hallucination_examples_limit"] = int(self.DEFAULT_REPORT_OPTIONS["hallucination_examples_limit"])

        raw_threshold_overrides = report_options.get("zone_threshold_overrides")
        clean_threshold_overrides: dict[str, dict[str, float]] = {}
        if isinstance(raw_threshold_overrides, dict):
            allowed_metric_keys = {
                "avg_mos",
                "avg_prosody",
                "avg_valence",
                "avg_arousal",
                "avg_wer",
                "avg_cer",
                "avg_ttfb_ms",
                "avg_latency_ms",
            }
            allowed_threshold_keys = {"good_min", "neutral_min", "good_max", "neutral_max"}
            for metric_key, maybe_values in raw_threshold_overrides.items():
                if metric_key not in allowed_metric_keys or not isinstance(maybe_values, dict):
                    continue
                cleaned_metric_values: dict[str, float] = {}
                for threshold_key, raw_value in maybe_values.items():
                    if threshold_key not in allowed_threshold_keys:
                        continue
                    try:
                        cleaned_metric_values[threshold_key] = float(raw_value)
                    except (TypeError, ValueError):
                        continue
                if cleaned_metric_values:
                    clean_threshold_overrides[metric_key] = cleaned_metric_values
        normalized["zone_threshold_overrides"] = clean_threshold_overrides

        return normalized

    def build_payload(
        self,
        comparison: Any,
        samples: list[Any],
        report_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build template context from comparison and sample rows."""
        normalized_options = self._normalize_report_options(report_options)
        grouped: dict[tuple[str, str, str, str], list[Any]] = defaultdict(list)
        for sample in samples:
            grouped[
                (
                    sample.provider,
                    sample.model,
                    sample.voice_id,
                    sample.voice_name or sample.voice_id,
                )
            ].append(sample)

        run_groups: dict[tuple[str, str, str, str], list[Any]] = defaultdict(list)
        for sample in samples:
            run_groups[
                (
                    sample.text,
                    sample.provider,
                    sample.model,
                    sample.voice_name or sample.voice_id,
                )
            ].append(sample)

        provider_rows: list[dict[str, Any]] = []
        hallucination_examples: list[dict[str, Any]] = []

        for (provider, model, voice_id, voice_name), provider_samples in grouped.items():
            mos_values = []
            valence_values = []
            arousal_values = []
            prosody_values = []
            wer_values = []
            cer_values = []
            latency_values = []
            ttfb_values = []
            cost_values = []

            for sample in provider_samples:
                m = sample.evaluation_metrics or {}
                mos_values.append(self._pick_metric(m, "MOS Score"))
                valence_values.append(self._pick_metric(m, "Valence"))
                arousal_values.append(self._pick_metric(m, "Arousal"))
                prosody_values.append(self._pick_metric(m, "Prosody Score"))
                wer_values.append(self._pick_metric(m, "WER"))
                cer_values.append(self._pick_metric(m, "CER"))
                latency_values.append(sample.latency_ms)
                ttfb_values.append(sample.ttfb_ms)
                cost_values.append(
                    self._pick_metric(
                        m,
                        "Cost Per 1M Characters",
                        "cost_per_1m_characters",
                        "cost_per_1m_chars",
                        "cost_per_1m",
                    )
                )

                wer_score = self._pick_metric(m, "WER")
                asr_text = m.get("ASR Transcript")
                if wer_score is not None and asr_text:
                    hallucination_examples.append(
                        {
                            "provider": provider,
                            "provider_display": self._humanize_identifier(provider),
                            "model": model,
                            "model_display": self._humanize_identifier(model),
                            "voice_name": voice_name,
                            "voice_display": self._humanize_identifier(voice_name),
                            "prompt": sample.text,
                            "prediction": asr_text,
                            "wer": wer_score,
                        }
                    )

            provider_display = self._humanize_identifier(provider)
            model_display = self._humanize_identifier(model)
            voice_display = self._humanize_identifier(voice_name)
            avg_latency_ms = self._safe_mean(latency_values)
            avg_ttfb_ms = self._safe_mean(ttfb_values)
            row = {
                "provider": provider,
                "provider_display": provider_display,
                "model": model,
                "model_display": model_display,
                "voice_id": voice_id,
                "voice_name": voice_name,
                "voice_display": voice_display,
                "variant_label": (
                    f"Provider: {provider_display} | "
                    f"Model: {model_display} | "
                    f"Voice: {voice_display}"
                ),
                "sample_count": len(provider_samples),
                "avg_mos": self._safe_mean(mos_values),
                "avg_valence": self._safe_mean(valence_values),
                "avg_arousal": self._safe_mean(arousal_values),
                "avg_prosody": self._safe_mean(prosody_values),
                "avg_wer": self._safe_mean(wer_values),
                "avg_cer": self._safe_mean(cer_values),
                "avg_latency_ms": avg_latency_ms,
                "avg_ttfb_ms": avg_ttfb_ms,
                "endpoint_type": self._endpoint_type(avg_ttfb_ms, avg_latency_ms),
                "cost_per_1m": self._safe_mean(cost_values),
            }
            provider_rows.append(row)

        provider_rows.sort(key=lambda r: ((r["avg_mos"] is None), -(r["avg_mos"] or 0)))
        hallucination_examples.sort(key=lambda e: e["wer"], reverse=True)
        if (
            normalized_options["include_hallucination"]
            and normalized_options["include_hallucination_examples"]
            and normalized_options["include_wer"]
        ):
            hallucination_examples = hallucination_examples[: normalized_options["hallucination_examples_limit"]]
        else:
            hallucination_examples = []

        run_variability_rows: list[dict[str, Any]] = []
        for (text, provider, model, voice_name), run_samples in run_groups.items():
            if len(run_samples) <= 1:
                continue

            snapshots: list[dict[str, Any]] = []
            for run_sample in sorted(run_samples, key=lambda s: (s.run_index, s.sample_index)):
                metrics = run_sample.evaluation_metrics or {}
                snapshots.append(
                    {
                        "run_index": (run_sample.run_index or 0) + 1,
                        "mos": self._pick_metric(metrics, "MOS Score"),
                        "prosody": self._pick_metric(metrics, "Prosody Score"),
                        "valence": self._pick_metric(metrics, "Valence"),
                        "arousal": self._pick_metric(metrics, "Arousal"),
                        "wer": self._pick_metric(metrics, "WER"),
                        "cer": self._pick_metric(metrics, "CER"),
                        "latency_ms": run_sample.latency_ms,
                        "ttfb_ms": run_sample.ttfb_ms,
                    }
                )

            mos_values = [s["mos"] for s in snapshots if s["mos"] is not None]
            target_mos = self._safe_mean(mos_values) if mos_values else None
            if target_mos is not None:
                representative = min(
                    snapshots,
                    key=lambda s: (
                        abs((s["mos"] if s["mos"] is not None else target_mos) - target_mos),
                        s["run_index"],
                    ),
                )
                best = max(
                    [s for s in snapshots if s["mos"] is not None],
                    key=lambda s: float(s["mos"]),
                )
                worst = min(
                    [s for s in snapshots if s["mos"] is not None],
                    key=lambda s: float(s["mos"]),
                )
            else:
                latency_values = [s["latency_ms"] for s in snapshots if s["latency_ms"] is not None]
                target_latency = self._safe_mean(latency_values) if latency_values else None
                representative = min(
                    snapshots,
                    key=lambda s: (
                        abs((s["latency_ms"] if s["latency_ms"] is not None else (target_latency or 0)) - (target_latency or 0)),
                        s["run_index"],
                    ),
                )
                best = min(
                    snapshots,
                    key=lambda s: (float(s["latency_ms"]) if s["latency_ms"] is not None else float("inf")),
                )
                worst = max(
                    snapshots,
                    key=lambda s: (float(s["latency_ms"]) if s["latency_ms"] is not None else float("-inf")),
                )

            run_variability_rows.append(
                {
                    "text": text,
                    "provider": provider,
                    "provider_display": self._humanize_identifier(provider),
                    "model": model,
                    "model_display": self._humanize_identifier(model),
                    "voice_name": voice_name,
                    "voice_display": self._humanize_identifier(voice_name),
                    "runs": len(snapshots),
                    "representative": representative,
                    "best": best,
                    "worst": worst,
                }
            )

        run_variability_rows.sort(
            key=lambda row: (
                row["provider"],
                row["model"],
                row["voice_name"],
                row["text"],
            )
        )

        provider_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in provider_rows:
            provider_groups[row["provider"]].append(row)

        provider_aggregate_rows: list[dict[str, Any]] = []
        metric_keys = [
            "avg_mos",
            "avg_valence",
            "avg_arousal",
            "avg_prosody",
            "avg_wer",
            "avg_cer",
            "avg_latency_ms",
            "avg_ttfb_ms",
            "cost_per_1m",
        ]
        for provider, rows in provider_groups.items():
            sample_count = sum((r.get("sample_count") or 0) for r in rows)
            aggregate_row: dict[str, Any] = {"provider": provider, "sample_count": sample_count}

            for mk in metric_keys:
                weighted_vals: list[tuple[float, int]] = []
                for r in rows:
                    value = r.get(mk)
                    if value is None:
                        continue
                    weight = r.get("sample_count") or 1
                    weighted_vals.append((float(value), int(weight)))

                if not weighted_vals:
                    aggregate_row[mk] = None
                else:
                    denom = sum(w for _, w in weighted_vals) or len(weighted_vals)
                    aggregate_row[mk] = sum(v * w for v, w in weighted_vals) / denom

            provider_aggregate_rows.append(aggregate_row)

        provider_aggregate_rows.sort(
            key=lambda r: ((r.get("avg_mos") is None), -(r.get("avg_mos") or 0))
        )

        metric_directions = {
            "avg_mos": True,
            "avg_valence": True,
            "avg_arousal": True,
            "avg_prosody": True,
            "avg_wer": False,
            "avg_cer": False,
            "avg_latency_ms": False,
            "avg_ttfb_ms": False,
        }
        metric_bounds: dict[str, tuple[float, float] | None] = {}
        for key in metric_directions:
            values = [float(r[key]) for r in provider_rows if r.get(key) is not None]
            metric_bounds[key] = (min(values), max(values)) if values else None

        for row in provider_rows:
            classes: dict[str, str] = {}
            for key, higher_better in metric_directions.items():
                value = row.get(key)
                bounds = metric_bounds.get(key)
                if value is None or bounds is None:
                    classes[key] = "metric-neutral"
                    continue
                low, high = bounds
                spread = high - low
                if spread <= 0:
                    classes[key] = "metric-neutral"
                    continue
                norm = (float(value) - low) / spread
                if not higher_better:
                    norm = 1 - norm
                if norm >= 0.67:
                    classes[key] = "metric-good"
                elif norm <= 0.33:
                    classes[key] = "metric-bad"
                else:
                    classes[key] = "metric-neutral"
            row["metric_classes"] = classes

        def _winner(rows: list[dict[str, Any]], key: str, mode: str) -> dict[str, Any] | None:
            valid = [r for r in rows if r.get(key) is not None]
            if not valid:
                return None
            if mode == "max":
                return max(valid, key=lambda r: float(r[key]))
            return min(valid, key=lambda r: float(r[key]))

        has_comparison_variants = len(provider_rows) > 1
        top_naturalness = _winner(provider_rows, "avg_mos", "max") if normalized_options["include_naturalness"] else None
        lowest_latency = _winner(provider_rows, "avg_latency_ms", "min") if normalized_options["include_latency"] else None
        lowest_hallucination = (
            _winner(provider_rows, "avg_wer", "min")
            if (
                normalized_options["include_hallucination"]
                and normalized_options["include_wer"]
            )
            else None
        )
        best_context = _winner(provider_rows, "avg_prosody", "max") if normalized_options["include_prosody"] else None

        recommendations = []
        if top_naturalness:
            recommendations.append(
                {
                    "use_case": "Customer Support Voice Agent",
                    "provider": top_naturalness["variant_label"],
                    "reason": f"Highest naturalness ({self._to_score(top_naturalness['avg_mos'])} MOS).",
                }
            )
        if lowest_latency:
            recommendations.append(
                {
                    "use_case": "Real-time Voice Agent",
                    "provider": lowest_latency["variant_label"],
                    "reason": f"Lowest latency ({self._to_ms(lowest_latency['avg_latency_ms'])} avg).",
                }
            )
        if lowest_hallucination:
            recommendations.append(
                {
                    "use_case": "High-accuracy Requirements",
                    "provider": lowest_hallucination["variant_label"],
                    "reason": f"Lowest WER ({self._to_pct(lowest_hallucination['avg_wer'])}).",
                }
            )
        if best_context:
            recommendations.append(
                {
                    "use_case": "Context-sensitive Applications",
                    "provider": best_context["variant_label"],
                    "reason": (
                        "Best prosody/context stability proxy "
                        f"({self._to_score(best_context['avg_prosody'], 3)})."
                    ),
                }
            )

        metric_definitions: list[dict[str, Any]] = [
            {
                "key": "avg_mos",
                "title": "MOS Score Ranking",
                "full_form": "Mean Opinion Score (MOS)",
                "subtitle": "Higher is better",
                "definition": "Perceived speech naturalness and quality on a 1-5 scale.",
                "higher_is_better": True,
                "min_value": 1.0,
                "max_value": 5.0,
                "format_kind": "score",
                "range_label": "Measured range: 1.0 to 5.0",
                "zone_thresholds": {"good_min": 4.0, "neutral_min": 3.0},
            },
            {
                "key": "avg_prosody",
                "title": "Prosody Score Ranking",
                "full_form": "Prosody Score",
                "subtitle": "Higher is better",
                "definition": "Expressiveness proxy based on rhythm, stress, and intonation stability.",
                "higher_is_better": True,
                "min_value": 0.0,
                "max_value": 1.0,
                "format_kind": "score",
                "range_label": "Measured range: 0.0 to 1.0",
                "zone_thresholds": {"good_min": 0.7, "neutral_min": 0.4},
            },
            {
                "key": "avg_valence",
                "title": "Valence Ranking",
                "full_form": "Valence",
                "subtitle": "Higher is better",
                "definition": "Estimated emotional polarity from negative to positive.",
                "higher_is_better": True,
                "min_value": -1.0,
                "max_value": 1.0,
                "format_kind": "score",
                "range_label": "Measured range: -1.0 to 1.0",
                "zone_thresholds": {"good_min": 0.3, "neutral_min": -0.2},
            },
            {
                "key": "avg_arousal",
                "title": "Arousal Ranking",
                "full_form": "Arousal",
                "subtitle": "Higher is better",
                "definition": "Estimated emotional intensity from calm to energetic.",
                "higher_is_better": True,
                "min_value": 0.0,
                "max_value": 1.0,
                "format_kind": "score",
                "range_label": "Measured range: 0.0 to 1.0",
                "zone_thresholds": {"good_min": 0.7, "neutral_min": 0.4},
            },
            {
                "key": "avg_wer",
                "title": "WER Ranking",
                "full_form": "Word Error Rate (WER)",
                "subtitle": "Lower is better",
                "definition": "Word-level transcription mismatch between prompt and ASR output.",
                "higher_is_better": False,
                "min_value": 0.0,
                "max_value": 1.0,
                "format_kind": "pct",
                "range_label": "Measured range: 0.0 to 1.0 (0% to 100%)",
                "zone_thresholds": {"good_max": 0.1, "neutral_max": 0.25},
            },
            {
                "key": "avg_cer",
                "title": "CER Ranking",
                "full_form": "Character Error Rate (CER)",
                "subtitle": "Lower is better",
                "definition": "Character-level transcription mismatch between prompt and ASR output.",
                "higher_is_better": False,
                "min_value": 0.0,
                "max_value": 1.0,
                "format_kind": "pct",
                "range_label": "Measured range: 0.0 to 1.0 (0% to 100%)",
                "zone_thresholds": {"good_max": 0.08, "neutral_max": 0.2},
            },
            {
                "key": "avg_ttfb_ms",
                "title": "TTFB Ranking",
                "full_form": "Time to First Byte (TTFB)",
                "subtitle": "Lower is better",
                "definition": "Time from request start to first audio byte received.",
                "higher_is_better": False,
                "min_value": None,
                "max_value": None,
                "format_kind": "ms",
                "range_label": "Measured range: dataset-dependent (milliseconds)",
                "zone_thresholds": {"good_max": 350.0, "neutral_max": 800.0},
            },
            {
                "key": "avg_latency_ms",
                "title": "Total Latency Ranking",
                "full_form": "Total Synthesis Latency",
                "subtitle": "Lower is better",
                "definition": "End-to-end time from request start to complete audio payload.",
                "higher_is_better": False,
                "min_value": None,
                "max_value": None,
                "format_kind": "ms",
                "range_label": "Measured range: dataset-dependent (milliseconds)",
                "zone_thresholds": {"good_max": 1500.0, "neutral_max": 3000.0},
            },
        ]

        threshold_overrides = normalized_options.get("zone_threshold_overrides") or {}
        if isinstance(threshold_overrides, dict):
            for metric in metric_definitions:
                metric_key = metric.get("key")
                if not metric_key:
                    continue
                override_values = threshold_overrides.get(metric_key)
                if not isinstance(override_values, dict):
                    continue
                merged_thresholds = dict(metric.get("zone_thresholds") or {})
                for threshold_key in ("good_min", "neutral_min", "good_max", "neutral_max"):
                    if threshold_key not in override_values:
                        continue
                    try:
                        merged_thresholds[threshold_key] = float(override_values[threshold_key])
                    except (TypeError, ValueError):
                        continue
                metric["zone_thresholds"] = merged_thresholds

        metric_sections: list[dict[str, Any]] = []
        for metric in metric_definitions:
            key = metric["key"]
            metric_visibility_option = {
                "avg_mos": "include_naturalness",
                "avg_prosody": "include_prosody",
                "avg_valence": "include_valence",
                "avg_arousal": "include_arousal",
                "avg_wer": "include_wer",
                "avg_cer": "include_cer",
                "avg_ttfb_ms": "include_ttfb",
                "avg_latency_ms": "include_latency",
            }.get(key)
            if metric_visibility_option and not normalized_options.get(metric_visibility_option, True):
                continue

            valid_rows = [
                {
                    "provider": r["provider"],
                    "voice_name": r["voice_name"],
                    "model": r["model"],
                    "variant_label": r["variant_label"],
                    "value": r.get(key),
                }
                for r in provider_rows
                if r.get(key) is not None
            ]
            if not valid_rows:
                continue

            valid_rows.sort(
                key=lambda r: float(r["value"]), reverse=bool(metric["higher_is_better"])
            )

            configured_min = metric.get("min_value")
            configured_max = metric.get("max_value")
            observed_vals = [float(r["value"]) for r in valid_rows]
            observed_min = min(observed_vals)
            observed_max = max(observed_vals)
            min_bound = float(configured_min) if configured_min is not None else observed_min
            max_bound = float(configured_max) if configured_max is not None else observed_max
            spread = max_bound - min_bound

            section_rows = []
            thresholds = metric.get("zone_thresholds") or {}
            for row in valid_rows:
                value = float(row["value"])
                if spread <= 0:
                    pct = 100.0
                else:
                    normalized = (value - min_bound) / spread
                    # Bar length represents raw magnitude for every metric:
                    # larger numeric value => longer bar, regardless of whether
                    # a metric is higher-is-better or lower-is-better.
                    pct = normalized * 100.0
                pct = max(8.0, min(100.0, pct))

                zone_class = "zone-neutral"
                if metric["higher_is_better"]:
                    good_min = thresholds.get("good_min")
                    neutral_min = thresholds.get("neutral_min")
                    if good_min is not None and value >= float(good_min):
                        zone_class = "zone-good"
                    elif neutral_min is not None and value >= float(neutral_min):
                        zone_class = "zone-neutral"
                    else:
                        zone_class = "zone-bad"
                else:
                    good_max = thresholds.get("good_max")
                    neutral_max = thresholds.get("neutral_max")
                    if good_max is not None and value <= float(good_max):
                        zone_class = "zone-good"
                    elif neutral_max is not None and value <= float(neutral_max):
                        zone_class = "zone-neutral"
                    else:
                        zone_class = "zone-bad"

                section_rows.append(
                    {
                        "provider": row["provider"],
                        "voice_name": row["voice_name"],
                        "model": row["model"],
                        "variant_label": row["variant_label"],
                        "value": value,
                        "display_value": self._format_metric_value(value, metric["format_kind"]),
                        "bar_pct": pct,
                        "zone_class": zone_class,
                    }
                )

            zone_gradient = "linear-gradient(90deg, #ef4444 0%, #f59e0b 50%, #16a34a 100%)"
            zone_labels = {
                "start": "Low",
                "middle": "Neutral",
                "end": "High",
            }
            zone_ticks: list[dict[str, Any]] = []

            def _threshold_to_pct(raw_threshold: Any) -> float | None:
                if raw_threshold is None:
                    return None
                try:
                    threshold = float(raw_threshold)
                except (TypeError, ValueError):
                    return None
                if spread <= 0:
                    return 50.0
                pct = ((threshold - min_bound) / spread) * 100.0
                return max(0.0, min(100.0, pct))

            if metric["higher_is_better"]:
                good_min = thresholds.get("good_min")
                neutral_min = thresholds.get("neutral_min")
                zone_labels = {
                    "start": (
                        f"Red: < {self._format_metric_value(float(neutral_min), metric['format_kind'])}"
                        if neutral_min is not None
                        else "Red: low values"
                    ),
                    "middle": (
                        "Neutral: "
                        f"{self._format_metric_value(float(neutral_min), metric['format_kind'])}"
                        f" - {self._format_metric_value(float(good_min), metric['format_kind'])}"
                        if (neutral_min is not None and good_min is not None)
                        else "Neutral: mid-range values"
                    ),
                    "end": (
                        f"Green: >= {self._format_metric_value(float(good_min), metric['format_kind'])}"
                        if good_min is not None
                        else "Green: high values"
                    ),
                }
                neutral_tick = _threshold_to_pct(neutral_min)
                good_tick = _threshold_to_pct(good_min)
                if neutral_tick is not None:
                    zone_ticks.append({"position_pct": neutral_tick, "label": "Neutral threshold"})
                if good_tick is not None:
                    zone_ticks.append({"position_pct": good_tick, "label": "Good threshold"})
            else:
                zone_gradient = "linear-gradient(90deg, #16a34a 0%, #f59e0b 50%, #ef4444 100%)"
                good_max = thresholds.get("good_max")
                neutral_max = thresholds.get("neutral_max")
                zone_labels = {
                    "start": (
                        f"Green: <= {self._format_metric_value(float(good_max), metric['format_kind'])}"
                        if good_max is not None
                        else "Green: low values"
                    ),
                    "middle": (
                        "Neutral: "
                        f"{self._format_metric_value(float(good_max), metric['format_kind'])}"
                        f" - {self._format_metric_value(float(neutral_max), metric['format_kind'])}"
                        if (good_max is not None and neutral_max is not None)
                        else "Neutral: mid-range values"
                    ),
                    "end": (
                        f"Red: > {self._format_metric_value(float(neutral_max), metric['format_kind'])}"
                        if neutral_max is not None
                        else "Red: high values"
                    ),
                }
                good_tick = _threshold_to_pct(good_max)
                neutral_tick = _threshold_to_pct(neutral_max)
                if good_tick is not None:
                    zone_ticks.append({"position_pct": good_tick, "label": "Good threshold"})
                if neutral_tick is not None:
                    zone_ticks.append({"position_pct": neutral_tick, "label": "Neutral threshold"})

            zone_ticks.sort(key=lambda t: float(t["position_pct"]))

            metric_sections.append(
                {
                    "title": metric["title"],
                    "full_form": metric["full_form"],
                    "subtitle": metric["subtitle"],
                    "definition": metric.get("definition"),
                    "range_label": (
                        f"{metric.get('range_label')} | Bar length represents raw metric magnitude"
                    ),
                    "zone_gradient": zone_gradient,
                    "zone_labels": zone_labels,
                    "zone_ticks": zone_ticks,
                    "rows": section_rows,
                }
            )

        summary = {
            "top_naturalness": top_naturalness,
            "lowest_latency": lowest_latency,
            "lowest_hallucination": lowest_hallucination,
            "best_context": best_context,
        }

        endpoint_modes = sorted({r["endpoint_type"] for r in provider_rows if r.get("endpoint_type")})

        aggregate_metric_columns = []
        if normalized_options["include_naturalness"]:
            aggregate_metric_columns.append({"key": "avg_mos", "label": "MOS", "format_kind": "score"})
        if normalized_options["include_valence"]:
            aggregate_metric_columns.append({"key": "avg_valence", "label": "Valence", "format_kind": "score"})
        if normalized_options["include_arousal"]:
            aggregate_metric_columns.append({"key": "avg_arousal", "label": "Arousal", "format_kind": "score"})
        if normalized_options["include_prosody"]:
            aggregate_metric_columns.append({"key": "avg_prosody", "label": "Prosody", "format_kind": "score"})
        if normalized_options["include_wer"]:
            aggregate_metric_columns.append({"key": "avg_wer", "label": "WER", "format_kind": "pct"})
        if normalized_options["include_cer"]:
            aggregate_metric_columns.append({"key": "avg_cer", "label": "CER", "format_kind": "pct"})
        if normalized_options["include_latency"]:
            aggregate_metric_columns.append({"key": "avg_latency_ms", "label": "Latency", "format_kind": "ms"})
        if normalized_options["include_ttfb"]:
            aggregate_metric_columns.append({"key": "avg_ttfb_ms", "label": "TTFB", "format_kind": "ms"})

        evaluation_dimensions: list[str] = []
        if normalized_options["include_naturalness"]:
            evaluation_dimensions.append("Naturalness (MOS - Mean Opinion Score)")
        if normalized_options["include_latency"] or normalized_options["include_ttfb"]:
            evaluation_dimensions.append("Latency performance")
        if normalized_options["include_wer"] or normalized_options["include_cer"]:
            evaluation_dimensions.append("Speech accuracy (WER/CER)")
        if normalized_options["include_valence"] or normalized_options["include_arousal"]:
            evaluation_dimensions.append("Emotional quality (Valence/Arousal)")
        if normalized_options["include_prosody"]:
            evaluation_dimensions.append("Prosody / context stability proxy")
        if normalized_options["include_endpoint"]:
            evaluation_dimensions.append("Endpoint behavior (streaming vs non-streaming, inferred)")

        total_runs_observed = len({s.run_index for s in samples})
        show_run_summary = normalized_options["show_runs"] and (
            total_runs_observed >= normalized_options["min_runs_to_show"]
        )

        metrics_glossary = [
            {
                "major_metric": "Naturalness",
                "sub_metric": "MOS",
                "full_form": "Mean Opinion Score",
                "description": "Perceived speech quality on a 1-5 scale.",
            },
            {
                "major_metric": "Speech Accuracy",
                "sub_metric": "WER",
                "full_form": "Word Error Rate",
                "description": "Word-level transcription mismatch between prompt and ASR output.",
            },
            {
                "major_metric": "Speech Accuracy",
                "sub_metric": "CER",
                "full_form": "Character Error Rate",
                "description": "Character-level mismatch between prompt and ASR output.",
            },
            {
                "major_metric": "Latency",
                "sub_metric": "TTFB",
                "full_form": "Time to First Byte",
                "description": "Time from API request start to first audio byte received.",
            },
            {
                "major_metric": "Latency",
                "sub_metric": "Total Latency",
                "full_form": "Total Synthesis Latency",
                "description": "Total time from API request start to full audio payload received.",
            },
            {
                "major_metric": "Emotion",
                "sub_metric": "Valence",
                "full_form": "Valence",
                "description": "Emotional polarity estimate (negative to positive).",
            },
            {
                "major_metric": "Emotion",
                "sub_metric": "Arousal",
                "full_form": "Arousal",
                "description": "Emotional intensity estimate (calm to energetic).",
            },
            {
                "major_metric": "Expressiveness",
                "sub_metric": "Prosody",
                "full_form": "Prosody Score",
                "description": "Rhythm, stress, and intonation stability proxy.",
            },
        ]
        qualitative_metrics = [
            m for m in metrics_glossary if m["major_metric"] in {"Naturalness", "Emotion", "Expressiveness"}
        ]
        quantitative_metrics = [
            m for m in metrics_glossary if m["major_metric"] in {"Speech Accuracy", "Latency"}
        ]

        disclaimer_sections = [
            {
                "title": "Latency Disclaimer",
                "points": [
                    "Reported latency and TTFB reflect benchmark-run conditions only and are sensitive to network routing, region, queue depth, and provider-side load at test time.",
                    "Cross-provider latency is directionally useful but not a strict SLA prediction for production traffic.",
                    "Client playback buffering, browser/media stack overhead, and streaming chunk behavior are not fully represented in server-side synthesis timings.",
                ],
            },
            {
                "title": "ASR / WER / CER Disclaimer",
                "points": [
                    "WER and CER are computed using an automated ASR reference transcript and can vary by accent, speaking rate, punctuation normalization, and domain vocabulary.",
                    "Lower WER/CER does not guarantee factual correctness; it measures transcription similarity, not semantic truthfulness.",
                    "Primary WER/CER in this report use entity-normalized scoring to reduce false penalties for numeric or currency phrasing differences; raw scores may be higher.",
                    "Hallucination examples are heuristic indicators and should be manually reviewed before operational decisions.",
                ],
            },
            {
                "title": "Audio Quality Metric Disclaimer",
                "points": [
                    "MOS, Valence, Arousal, and Prosody are model-derived proxies and may not perfectly align with human preference in all domains.",
                    "Metrics can drift with prompt style, sentence length, and voice persona; compare providers on matched prompts and run counts.",
                    "Single-run results are less stable; multi-run comparisons are recommended for procurement or policy decisions.",
                    "For repeated transcripts, this report shows a representative run plus best/worst outliers to highlight variability without duplicating every sample.",
                ],
            },
        ]

        methodology_sections = [
            {
                "title": "Data Collection",
                "body": (
                    "Voice samples are synthesized from standardized prompts spanning conversational dialogue, numerical entities, "
                    "and context-sensitive instructions. Each provider/model combination is evaluated on comparable text inputs."
                ),
                "bullets": [],
            },
            {
                "title": "Metrics Calculation",
                "body": "This report aggregates automatically computed voice quality and performance metrics.",
                "bullets": [
                    "MOS (Mean Opinion Score): Per-sample quality proxy on a 1-5 scale.",
                    "Valence / Arousal: Emotional polarity and activation estimates from audio.",
                    "Prosody Score: Expressiveness proxy from acoustic variation and emotional intensity.",
                    "WER / CER: ASR transcript distance versus source prompt text (entity-normalized variant used for primary ranking).",
                    "Latency / TTFB: End-to-end synthesis latency and first-byte response time.",
                    "Total latency formula: request_start -> first_byte (TTFB) + first_byte -> final_audio_byte.",
                    "Per-transcript run variability: representative run chosen near mean quality, plus best and worst outlier runs.",
                ],
            },
            {
                "title": "Testing Infrastructure",
                "body": (
                    "Benchmarks run via the EfficientAI Voice Playground evaluation pipeline. "
                    "Timing values include service-call overhead and can vary by network path and provider availability."
                ),
                "bullets": [],
            },
            {
                "title": "Evaluation Framework",
                "body": (
                    "Provider rankings and recommendations are computed by deterministic rule logic over available metrics "
                    "(for example: naturalness=max MOS, hallucination=min WER, latency=min avg latency)."
                ),
                "bullets": [],
            },
        ]

        provider_overview_map: dict[str, dict[str, Any]] = {}
        for row in provider_rows:
            provider_key = row["provider_display"]
            bucket = provider_overview_map.setdefault(
                provider_key,
                {
                    "provider": row["provider_display"],
                    "models": set(),
                    "voices": set(),
                    "sample_count": 0,
                },
            )
            bucket["models"].add(row["model_display"])
            bucket["voices"].add(row["voice_display"])
            bucket["sample_count"] += int(row.get("sample_count") or 0)

        provider_overview = []
        for provider_name in sorted(provider_overview_map.keys()):
            bucket = provider_overview_map[provider_name]
            provider_overview.append(
                {
                    "provider": bucket["provider"],
                    "models": ", ".join(sorted(bucket["models"])),
                    "voices": ", ".join(sorted(bucket["voices"])),
                    "sample_count": bucket["sample_count"],
                }
            )

        return {
            "title": "Voice AI Benchmark Report",
            "subtitle": "TTS Provider Comparison",
            "generated_by": "EfficientAI",
            "logo_data_uri": self._logo_data_uri,
            "generated_at": datetime.now(timezone.utc),
            "comparison_id": str(comparison.id),
            "simulation_id": comparison.simulation_id,
            "comparison_name": comparison.name,
            "providers_tested": sorted({r["provider_display"] for r in provider_rows}),
            "voices_tested": sorted({r["voice_display"] for r in provider_rows}),
            "tested_variants": sorted({r["variant_label"] for r in provider_rows}),
            "provider_overview": provider_overview,
            "num_runs": comparison.num_runs or 1,
            "total_runs_observed": total_runs_observed,
            "show_run_summary": show_run_summary,
            "sample_count": len(samples),
            "endpoint_modes": endpoint_modes,
            "summary": summary,
            "has_comparison_variants": has_comparison_variants,
            "provider_rows": provider_rows,
            "provider_aggregate_rows": provider_aggregate_rows,
            "aggregate_metric_columns": aggregate_metric_columns,
            "evaluation_dimensions": evaluation_dimensions,
            "show_endpoint_column": normalized_options["include_endpoint"],
            "show_hallucination_section": normalized_options["include_hallucination"],
            "metric_sections": metric_sections,
            "hallucination_examples": hallucination_examples,
            "metrics_glossary": metrics_glossary,
            "qualitative_metrics": qualitative_metrics,
            "quantitative_metrics": quantitative_metrics,
            "run_variability_rows": run_variability_rows,
            "has_run_variability": len(run_variability_rows) > 0,
            "recommendations": recommendations,
            "disclaimer_sections": (
                disclaimer_sections if normalized_options["include_disclaimer_sections"] else []
            ),
            "methodology_sections": (
                methodology_sections if normalized_options["include_methodology_sections"] else []
            ),
            "report_options": normalized_options,
        }

    _weasyprint_deps_checked = False

    @staticmethod
    def _ensure_weasyprint_system_deps():
        """One-shot check/install of system libraries required by WeasyPrint."""
        if VoicePlaygroundReportService._weasyprint_deps_checked:
            return
        VoicePlaygroundReportService._weasyprint_deps_checked = True

        import ctypes.util
        if ctypes.util.find_library("gobject-2.0"):
            return

        import shutil, subprocess, os
        if shutil.which("apt-get") and os.geteuid() == 0:
            from loguru import logger
            logger.info("[PDF] WeasyPrint system libs missing – installing via apt-get...")
            try:
                subprocess.check_call(
                    ["apt-get", "update", "-qq"],
                    timeout=120,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                subprocess.check_call(
                    [
                        "apt-get", "install", "-y", "-qq",
                        "libgobject-2.0-0", "libpango-1.0-0", "libpangocairo-1.0-0",
                        "libcairo2", "libgdk-pixbuf-2.0-0", "libffi-dev", "shared-mime-info",
                    ],
                    timeout=120,
                )
                logger.info("[PDF] WeasyPrint system libs installed successfully")
            except Exception as e:
                logger.warning(f"[PDF] Auto-install of system libs failed: {e}")

    def render_pdf(self, payload: dict[str, Any]) -> bytes:
        """Render report payload to PDF bytes."""
        self._ensure_weasyprint_system_deps()

        try:
            from weasyprint import HTML
        except ImportError as exc:
            raise RuntimeError(
                "PDF generation requires weasyprint. Install dependencies and retry."
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                f"WeasyPrint system libraries missing: {exc}. "
                "Install them with: apt-get install -y libgobject-2.0-0 libpango-1.0-0 "
                "libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info"
            ) from exc

        template = self._jinja_env.get_template("reports/voice_playground_report.html")
        html_content = template.render(**payload, service=self)
        return HTML(string=html_content).write_pdf()


voice_playground_report_service = VoicePlaygroundReportService()
