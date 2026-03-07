"""PDF report generation service for Voice Playground comparisons."""

from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


class VoicePlaygroundReportService:
    """Build and render comprehensive Voice Playground benchmark reports."""

    def __init__(self) -> None:
        templates_dir = Path(__file__).parent.parent / "templates"
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
        project_root = Path(__file__).parent.parent.parent
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

    def build_payload(self, comparison: Any, samples: list[Any]) -> dict[str, Any]:
        """Build template context from comparison and sample rows."""
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
                            "model": model,
                            "voice_name": voice_name,
                            "prompt": sample.text,
                            "prediction": asr_text,
                            "wer": wer_score,
                        }
                    )

            row = {
                "provider": provider,
                "model": model,
                "voice_id": voice_id,
                "voice_name": voice_name,
                "variant_label": f"{provider} / {voice_name} ({model})",
                "sample_count": len(provider_samples),
                "avg_mos": self._safe_mean(mos_values),
                "avg_valence": self._safe_mean(valence_values),
                "avg_arousal": self._safe_mean(arousal_values),
                "avg_prosody": self._safe_mean(prosody_values),
                "avg_wer": self._safe_mean(wer_values),
                "avg_cer": self._safe_mean(cer_values),
                "avg_latency_ms": self._safe_mean(latency_values),
                "avg_ttfb_ms": self._safe_mean(ttfb_values),
                "cost_per_1m": self._safe_mean(cost_values),
            }
            provider_rows.append(row)

        provider_rows.sort(key=lambda r: ((r["avg_mos"] is None), -(r["avg_mos"] or 0)))
        hallucination_examples.sort(key=lambda e: e["wer"], reverse=True)
        hallucination_examples = hallucination_examples[:5]

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
                    "model": model,
                    "voice_name": voice_name,
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

        def _winner(rows: list[dict[str, Any]], key: str, mode: str) -> dict[str, Any] | None:
            valid = [r for r in rows if r.get(key) is not None]
            if not valid:
                return None
            if mode == "max":
                return max(valid, key=lambda r: float(r[key]))
            return min(valid, key=lambda r: float(r[key]))

        top_naturalness = _winner(provider_rows, "avg_mos", "max")
        lowest_latency = _winner(provider_rows, "avg_latency_ms", "min")
        lowest_hallucination = _winner(provider_rows, "avg_wer", "min")
        best_cost = _winner(provider_rows, "cost_per_1m", "min")
        best_context = _winner(provider_rows, "avg_prosody", "max")

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
        if best_cost:
            recommendations.append(
                {
                    "use_case": "Low-cost Applications",
                    "provider": best_cost["variant_label"],
                    "reason": f"Lowest estimated cost (${best_cost['cost_per_1m']:.2f} per 1M chars).",
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
                "subtitle": "Higher is better",
                "higher_is_better": True,
                "min_value": 1.0,
                "max_value": 5.0,
                "format_kind": "score",
                "range_label": "Measured range: 1.0 to 5.0",
            },
            {
                "key": "avg_prosody",
                "title": "Prosody Score Ranking",
                "subtitle": "Higher is better",
                "higher_is_better": True,
                "min_value": 0.0,
                "max_value": 1.0,
                "format_kind": "score",
                "range_label": "Measured range: 0.0 to 1.0",
            },
            {
                "key": "avg_valence",
                "title": "Valence Ranking",
                "subtitle": "Higher is better",
                "higher_is_better": True,
                "min_value": -1.0,
                "max_value": 1.0,
                "format_kind": "score",
                "range_label": "Measured range: -1.0 to 1.0",
            },
            {
                "key": "avg_arousal",
                "title": "Arousal Ranking",
                "subtitle": "Higher is better",
                "higher_is_better": True,
                "min_value": 0.0,
                "max_value": 1.0,
                "format_kind": "score",
                "range_label": "Measured range: 0.0 to 1.0",
            },
            {
                "key": "avg_wer",
                "title": "WER Ranking",
                "subtitle": "Lower is better",
                "higher_is_better": False,
                "min_value": 0.0,
                "max_value": 1.0,
                "format_kind": "pct",
                "range_label": "Measured range: 0.0 to 1.0 (0% to 100%)",
            },
            {
                "key": "avg_cer",
                "title": "CER Ranking",
                "subtitle": "Lower is better",
                "higher_is_better": False,
                "min_value": 0.0,
                "max_value": 1.0,
                "format_kind": "pct",
                "range_label": "Measured range: 0.0 to 1.0 (0% to 100%)",
            },
            {
                "key": "avg_ttfb_ms",
                "title": "TTFB Ranking",
                "subtitle": "Lower is better",
                "higher_is_better": False,
                "min_value": None,
                "max_value": None,
                "format_kind": "ms",
                "range_label": "Measured range: dataset-dependent (milliseconds)",
            },
            {
                "key": "avg_latency_ms",
                "title": "Total Latency Ranking",
                "subtitle": "Lower is better",
                "higher_is_better": False,
                "min_value": None,
                "max_value": None,
                "format_kind": "ms",
                "range_label": "Measured range: dataset-dependent (milliseconds)",
            },
        ]

        metric_sections: list[dict[str, Any]] = []
        for metric in metric_definitions:
            key = metric["key"]
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

                section_rows.append(
                    {
                        "provider": row["provider"],
                        "voice_name": row["voice_name"],
                        "model": row["model"],
                        "variant_label": row["variant_label"],
                        "value": value,
                        "display_value": self._format_metric_value(value, metric["format_kind"]),
                        "bar_pct": pct,
                    }
                )

            metric_sections.append(
                {
                    "title": metric["title"],
                    "subtitle": metric["subtitle"],
                    "range_label": (
                        f"{metric.get('range_label')} | Bar length represents raw metric magnitude"
                    ),
                    "rows": section_rows,
                }
            )

        summary = {
            "top_naturalness": top_naturalness,
            "lowest_latency": lowest_latency,
            "lowest_hallucination": lowest_hallucination,
            "best_cost_efficiency": best_cost,
            "best_context": best_context,
        }

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
            {
                "title": "Cost and Recommendation Disclaimer",
                "points": [
                    "Cost values are included only when available in current benchmark metadata and may not include provider minimums, surcharges, or burst pricing.",
                    "Recommendations are deterministic outputs from configured metric rules and should be validated against your product constraints, compliance needs, and customer profile.",
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

        return {
            "title": "Voice AI Benchmark Report",
            "subtitle": "TTS Provider Comparison",
            "generated_by": "EfficientAI",
            "logo_data_uri": self._logo_data_uri,
            "generated_at": datetime.now(timezone.utc),
            "comparison_id": str(comparison.id),
            "simulation_id": comparison.simulation_id,
            "comparison_name": comparison.name,
            "providers_tested": sorted({s.provider for s in samples}),
            "voices_tested": sorted({(s.voice_name or s.voice_id) for s in samples}),
            "num_runs": comparison.num_runs or 1,
            "sample_count": len(samples),
            "summary": summary,
            "provider_rows": provider_rows,
            "provider_aggregate_rows": provider_aggregate_rows,
            "metric_sections": metric_sections,
            "hallucination_examples": hallucination_examples,
            "run_variability_rows": run_variability_rows,
            "has_run_variability": len(run_variability_rows) > 0,
            "has_multilingual_data": False,
            "multilingual_rows": [],
            "has_instruction_data": False,
            "instruction_rows": [],
            "cost_rows": [r for r in provider_rows if r.get("cost_per_1m") is not None],
            "recommendations": recommendations,
            "disclaimer_sections": disclaimer_sections,
            "methodology_sections": methodology_sections,
        }

    def render_pdf(self, payload: dict[str, Any]) -> bytes:
        """Render report payload to PDF bytes."""
        try:
            from weasyprint import HTML
        except ImportError as exc:
            raise RuntimeError(
                "PDF generation requires weasyprint. Install dependencies and retry."
            ) from exc

        template = self._jinja_env.get_template("reports/voice_playground_report.html")
        html_content = template.render(**payload, service=self)
        return HTML(string=html_content).write_pdf()


voice_playground_report_service = VoicePlaygroundReportService()
