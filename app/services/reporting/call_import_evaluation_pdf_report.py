"""PDF report rendering for Call Import evaluation results."""

from __future__ import annotations

import html
import io
import math
import re
import textwrap
from urllib.parse import quote
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from loguru import logger

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
)
from app.models.schemas import MetricFailurePolicy
from app.services.metric_failure_policy import is_metric_failure

# WeasyPrint layout is expensive with many page-break-avoid blocks; keep PDF FD bounded.
_PDF_FD_MAX_METRIC_GROUPS = 12
_PDF_FD_MAX_CLUSTER_DETAIL = 2
_PDF_FD_OBSERVATION_MAX_CHARS = 280
_PDF_PROMPT_IMPROVEMENTS_MAX = 5
_PROMPT_IMPROVEMENT_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _sort_prompt_improvement_suggestions(
    suggestions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        suggestions,
        key=lambda item: (
            _PROMPT_IMPROVEMENT_PRIORITY_RANK.get(
                str(item.get("priority") or "medium").strip().lower(),
                1,
            ),
            -float(item.get("share_pct") or 0),
        ),
    )


def _prompt_improvement_change_type(item: dict[str, Any]) -> str:
    change_type = str(item.get("change_type") or "").strip().lower()
    anchor_excerpt = str(item.get("anchor_excerpt") or "").strip()
    if change_type not in {"edit", "add"}:
        change_type = "edit" if anchor_excerpt else "add"
    return change_type


def _clamp_prose_to_sentences(
    text: str,
    *,
    max_sentences: int = 3,
    max_chars: int = 300,
) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    cleaned = re.sub(r"\s*\n+\s*", " ", cleaned).strip()
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
        if sentence.strip()
    ]
    if sentences:
        result = " ".join(sentences[:max_sentences]).strip()
    else:
        result = cleaned
    if len(result) > max_chars:
        trimmed = result[: max_chars - 3].rsplit(" ", 1)[0].rstrip(".,;:")
        result = f"{trimmed}..." if trimmed else result[:max_chars]
    return result


@dataclass
class MetricReportSummary:
    id: str
    name: str
    metric_type: str
    description: str
    evaluated_count: int = 0
    flagged_count: int = 0
    numeric_values: list[float] = field(default_factory=list)
    value_counts: dict[str, int] = field(default_factory=dict)
    rationales: list[tuple[str, str]] = field(default_factory=list)
    is_business_metric: bool = False
    weekly_delta_label: str | None = None
    weekly_delta_detail: str | None = None
    weekly_delta_why: str | None = None
    group_name: str = "Quality Metrics"


class CallImportEvaluationPdfReportService:
    """Render external/internal Quality Metric Audit PDFs.

    WeasyPrint renders styled HTML when system libraries are available.
    A small built-in PDF renderer keeps the endpoint usable when native
    PDF dependencies are missing at runtime.
    """

    def render_pdf(
        self,
        *,
        vendor_name: str,
        call_import: CallImport,
        evaluation: CallImportEvaluation,
        metrics: list[Metric],
        rows: list[tuple[CallImportEvaluationRow, CallImportRow]],
        generated_at: datetime | None = None,
        internal: bool = False,
        logo_data_uris: list[str] | dict[str, str] | None = None,
        custom_heading: str | None = None,
        include_weekly_delta: bool = False,
        period_delta_by_metric: dict[str, dict[str, str]] | None = None,
        use_case: str | None = None,
        period_display: str | None = None,
        total_metric_count: int | None = None,
        report_config: dict[str, Any] | None = None,
        narrative: dict[str, Any] | None = None,
        audit_summary: str | None = None,
        metric_insights: dict[str, str] | None = None,
        benchmark_context: dict[str, str] | None = None,
        generated_user_insights: list[dict[str, Any]] | None = None,
        user_insights_overview: str | None = None,
        metric_clusters: dict[str, Any] | None = None,
        metric_clusters_overview: str | None = None,
        prompt_improvements: dict[str, Any] | None = None,
        failure_policies: dict[str, Any] | None = None,
        platform_base_url: str | None = None,
    ) -> bytes:
        generated_at = generated_at or datetime.now(timezone.utc)
        summaries = self._summarize_metrics(
            metrics, rows, failure_policies=failure_policies
        )
        weekly_delta_meta = None
        if include_weekly_delta:
            if period_delta_by_metric:
                self._attach_period_deltas(period_delta_by_metric, summaries)
            else:
                weekly_delta_meta = self._attach_weekly_deltas(metrics, rows, summaries)
        title = "Internal Quality Metric Audit" if internal else "Quality Metric Audit"
        payload = {
            "title": title,
            "subtitle": "Call Import Evaluation Report",
            "vendor_name": vendor_name,
            "generated_at": generated_at.strftime("%b %d, %Y %H:%M UTC"),
            "generated_at_iso": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
            "logo_data_uris": logo_data_uris or {},
            "custom_heading": (custom_heading or "").strip() or None,
            "call_import": call_import,
            "evaluation": evaluation,
            "metrics": summaries,
            "rows": rows,
            "internal": internal,
            "completion_rate": self._percent(
                evaluation.completed_rows, evaluation.total_rows
            ),
            "include_weekly_delta": include_weekly_delta,
            "weekly_delta_meta": weekly_delta_meta,
            "use_case": (use_case or "").strip() or None,
            "period_display": (period_display or "").strip() or "Not specified",
            "total_metric_count": total_metric_count or len(metrics),
            "report_config": report_config or {},
            "narrative": narrative or {},
            "audit_summary": (audit_summary or "").strip() or None,
            "metric_insights": metric_insights or {},
            "benchmark_context": benchmark_context or None,
            "generated_user_insights": generated_user_insights or [],
            "user_insights_overview": (user_insights_overview or "").strip() or None,
            "metric_clusters": metric_clusters or {},
            "metric_clusters_overview": (metric_clusters_overview or "").strip() or None,
            "prompt_improvements": prompt_improvements or {},
            "platform_base_url": (platform_base_url or "").strip().rstrip("/") or None,
            "call_import_id": str(call_import.id),
            "evaluation_id": str(evaluation.id),
        }
        html_content = self._render_html(payload)
        pdf_bytes = self._render_weasyprint(
            html_content,
            label=f"evaluation={getattr(evaluation, 'id', '')}",
        )
        if pdf_bytes:
            return pdf_bytes
        return self._render_basic_pdf(self._plain_text_lines(payload))

    def _summarize_metrics(
        self,
        metrics: list[Metric],
        rows: list[tuple[CallImportEvaluationRow, CallImportRow]],
        failure_policies: dict[str, Any] | None = None,
    ) -> list[MetricReportSummary]:
        summaries = [
            MetricReportSummary(
                id=str(metric.id),
                name=metric.name,
                metric_type=metric.metric_type,
                description=metric.description or "",
                is_business_metric=self._is_user_insight_metric(metric),
                group_name=self._metric_group_name(metric),
            )
            for metric in metrics
        ]
        by_id = {summary.id: summary for summary in summaries}
        metrics_by_id = {str(metric.id): metric for metric in metrics}

        for eval_row, source_row in rows:
            if getattr(eval_row, "status", None) != "completed":
                continue
            scores = eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
            for metric_id, summary in by_id.items():
                metric = metrics_by_id.get(metric_id)
                score = scores.get(metric_id)
                if not isinstance(score, dict):
                    continue
                value = self._score_value(score, metric)
                if value is None or score.get("skipped"):
                    continue
                summary.evaluated_count += 1
                label = self._value_label(value)
                summary.value_counts[label] = summary.value_counts.get(label, 0) + 1
                number = self._coerce_number(value)
                if number is not None and not isinstance(value, bool):
                    summary.numeric_values.append(number)
                policy_raw = (failure_policies or {}).get(metric_id)
                policy = (
                    policy_raw
                    if isinstance(policy_raw, MetricFailurePolicy)
                    else (
                        MetricFailurePolicy.model_validate(policy_raw)
                        if isinstance(policy_raw, dict)
                        else None
                    )
                )
                is_failure = (
                    is_metric_failure(eval_row, metric, policy)
                    if metric is not None and policy is not None
                    else self._is_flagged(value)
                )
                if is_failure:
                    summary.flagged_count += 1
                    rationale = score.get("rationale")
                    if isinstance(rationale, str) and rationale.strip():
                        summary.rationales.append(
                            (source_row.conversation_id, rationale.strip())
                        )

        return summaries

    def _attach_period_deltas(
        self,
        period_delta_by_metric: dict[str, dict[str, str]],
        summaries: list[MetricReportSummary],
    ) -> None:
        for summary in summaries:
            delta = period_delta_by_metric.get(summary.id) or {}
            summary.weekly_delta_label = delta.get("label") or "No previous-week baseline"
            summary.weekly_delta_detail = delta.get("detail") or ""
            summary.weekly_delta_why = (delta.get("why") or "").strip() or None

    def _is_user_insight_metric(self, metric: Metric) -> bool:
        if (getattr(metric, "metric_category", "quality") or "quality") == "user_insight":
            return True
        text = " ".join(
            str(part or "").lower()
            for part in (
                getattr(metric, "name", ""),
                getattr(metric, "description", ""),
            )
        )
        normalized = text.replace("-", " ").replace("_", " ")
        legacy_phrases = (
            "call context",
            "caller context",
            "product identification",
            "out of scope",
            "identity match",
            "user identity",
            "caller identity",
            "frustration trigger",
            "video call offer",
            "video call reception",
        )
        return any(phrase in normalized for phrase in legacy_phrases)

    def _metric_group_name(self, metric: Metric) -> str:
        tags = getattr(metric, "tags", None)
        if isinstance(tags, list) and tags:
            first = str(tags[0]).replace("_", " ").replace("-", " ").strip()
            if first:
                return first.title()
        return "Quality Metrics"

    def _attach_weekly_deltas(
        self,
        metrics: list[Metric],
        rows: list[tuple[CallImportEvaluationRow, CallImportRow]],
        summaries: list[MetricReportSummary],
    ) -> dict[str, Any] | None:
        dated_rows = [
            (eval_row, source_row)
            for eval_row, source_row in rows
            if eval_row.status == "completed" and source_row.recording_date
        ]
        missing_dates = sum(
            1
            for eval_row, source_row in rows
            if eval_row.status == "completed" and not source_row.recording_date
        )
        if not dated_rows:
            for summary in summaries:
                summary.weekly_delta_label = "No recording-date baseline"
                summary.weekly_delta_detail = "Completed rows have no recording date."
            return {"missing_dates": missing_dates}

        latest_date = max(source_row.recording_date for _, source_row in dated_rows)
        week_start = latest_date - timedelta(days=latest_date.weekday())
        next_week_start = week_start + timedelta(days=7)
        previous_week_start = week_start - timedelta(days=7)

        current_rows = [
            pair
            for pair in dated_rows
            if week_start <= pair[1].recording_date < next_week_start
        ]
        previous_rows = [
            pair
            for pair in dated_rows
            if previous_week_start <= pair[1].recording_date < week_start
        ]

        current_by_id = {
            summary.id: summary
            for summary in self._summarize_metrics(metrics, current_rows)
        }
        previous_by_id = {
            summary.id: summary
            for summary in self._summarize_metrics(metrics, previous_rows)
        }

        for summary in summaries:
            current = current_by_id.get(summary.id)
            previous = previous_by_id.get(summary.id)
            if (
                current is None
                or previous is None
                or current.evaluated_count <= 0
                or previous.evaluated_count <= 0
            ):
                summary.weekly_delta_label = "No previous-week baseline"
                summary.weekly_delta_detail = (
                    "Not enough dated scores in the current or previous week."
                )
                continue

            current_value = self._primary_metric_percent(current)
            previous_value = self._primary_metric_percent(previous)
            delta = current_value - previous_value
            sign = "+" if delta >= 0 else ""
            summary.weekly_delta_label = f"{sign}{delta:.1f} pp"
            summary.weekly_delta_detail = (
                f"Current week {current_value:.1f}% vs previous week "
                f"{previous_value:.1f}%"
            )

        return {
            "latest_date": latest_date,
            "week_start": week_start,
            "previous_week_start": previous_week_start,
            "current_count": len(current_rows),
            "previous_count": len(previous_rows),
            "missing_dates": missing_dates,
        }

    def _score_value(self, score: dict[str, Any], metric: Metric | None) -> Any:
        if metric is not None and metric.selection_mode and not metric.parent_metric_id:
            if metric.selection_mode == "multi_label":
                selected = score.get("selected_child_names")
                if isinstance(selected, list):
                    return "; ".join(str(item) for item in selected if item)
            return score.get("chosen_child_name") or score.get("value")
        return score.get("value")

    def _is_flagged(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        number = self._coerce_number(value)
        if number is not None:
            return number < 0.5
        if isinstance(value, str):
            return value.strip().lower() in {"fail", "failed", "false", "bad", "yes"}
        return False

    def _coerce_number(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    def _value_label(self, value: Any) -> str:
        if isinstance(value, bool):
            return "Flagged" if value else "Clear"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    def _percent(self, numerator: int, denominator: int) -> str:
        if denominator <= 0:
            return "0%"
        return f"{(numerator / denominator) * 100:.1f}%"

    def _top_distribution(self, summary: MetricReportSummary) -> str:
        if not summary.value_counts:
            return "No completed scores"
        parts = sorted(summary.value_counts.items(), key=lambda item: (-item[1], item[0]))
        return ", ".join(f"{label}: {count}" for label, count in parts[:4])

    def _top_distribution_with_percentages(self, summary: MetricReportSummary) -> str:
        if not summary.value_counts or summary.evaluated_count <= 0:
            return "No completed scores"
        parts = sorted(summary.value_counts.items(), key=lambda item: (-item[1], item[0]))
        return ", ".join(
            f"{label}: {count} ({self._percent(count, summary.evaluated_count)})"
            for label, count in parts[:4]
        )

    def _measurement_label(self, summary: MetricReportSummary) -> str:
        if summary.numeric_values:
            return "Numeric score averaged across evaluated calls"
        labels = {label.lower() for label in summary.value_counts.keys()}
        if labels and labels.issubset({"flagged", "clear"}):
            return "Boolean metric measured as flagged-call percentage"
        return "Categorical metric measured as response distribution"

    def _metric_direction_label(self, summary: MetricReportSummary) -> str:
        if summary.numeric_values:
            return "Higher score is better"
        return "Lower rate is better"

    def _metric_result(self, summary: MetricReportSummary) -> str:
        if summary.numeric_values:
            avg = sum(summary.numeric_values) / len(summary.numeric_values)
            if 0 <= avg <= 1:
                return f"Average {avg:.2f} ({avg * 100:.1f}%)"
            return f"Average {avg:.2f}"
        return self._top_distribution(summary)

    def _primary_metric_percent(self, summary: MetricReportSummary) -> float:
        if summary.numeric_values:
            avg = sum(summary.numeric_values) / len(summary.numeric_values)
            if 0 <= avg <= 1:
                return avg * 100
            return max(0.0, min(avg, 100.0))
        if summary.evaluated_count <= 0:
            return 0.0
        return (summary.flagged_count / summary.evaluated_count) * 100

    def _primary_metric_label(self, summary: MetricReportSummary) -> str:
        percent = self._primary_metric_percent(summary)
        if summary.numeric_values:
            return f"{percent:.1f}%"
        return self._percent(summary.flagged_count, summary.evaluated_count)

    def _distribution_bars_html(self, summary: MetricReportSummary) -> str:
        if not summary.value_counts or summary.evaluated_count <= 0:
            return "<div class='empty-bars'>No completed scores to graph.</div>"
        parts = sorted(summary.value_counts.items(), key=lambda item: (-item[1], item[0]))
        bars = []
        for label, count in parts[:6]:
            pct = (count / summary.evaluated_count) * 100
            bars.append(
                f"""
                <div class="dist-row">
                  <div class="dist-label">{html.escape(label)}</div>
                  <div class="dist-track"><div class="dist-fill" style="width: {pct:.1f}%"></div></div>
                  <div class="dist-value">{count} · {pct:.1f}%</div>
                </div>
                """
            )
        return "".join(bars)

    def _insight_distribution_table_html(self, summary: MetricReportSummary) -> str:
        if not summary.value_counts or summary.evaluated_count <= 0:
            return "<p class='empty-bars'>No completed insight classifications.</p>"
        rows = []
        for label, count in sorted(
            summary.value_counts.items(), key=lambda item: (-item[1], item[0])
        )[:8]:
            pct = (count / summary.evaluated_count) * 100
            rows.append(
                f"""
                <tr>
                  <td>{html.escape(label)}</td>
                  <td>{pct:.1f}%</td>
                  <td><div class="insight-track"><div class="insight-fill" style="width: {pct:.1f}%"></div></div></td>
                  <td>{count}</td>
                </tr>
                """
            )
        return (
            "<table class='insight-table'>"
            "<thead><tr><th>Category</th><th>Share</th><th>Distribution</th><th>Calls</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    def _generated_insight_distribution_table_html(
        self, categories: list[dict[str, Any]]
    ) -> str:
        if not categories:
            return "<p class='empty-bars'>No categories identified.</p>"
        rows = []
        for cat in categories[:8]:
            if not isinstance(cat, dict):
                continue
            label = str(cat.get("label") or "").strip()
            if not label:
                continue
            count = int(cat.get("count") or 0)
            pct = float(cat.get("share_pct") or 0.0)
            rows.append(
                f"""
                <tr>
                  <td>{html.escape(label)}</td>
                  <td>{pct:.1f}%</td>
                  <td><div class="insight-track"><div class="insight-fill" style="width: {pct:.1f}%"></div></div></td>
                  <td>{count}</td>
                </tr>
                """
            )
        if not rows:
            return "<p class='empty-bars'>No categories identified.</p>"
        return (
            "<table class='insight-table'>"
            "<thead><tr><th>Category</th><th>Share</th><th>Distribution</th><th>Calls</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    def _evaluation_call_deep_link(
        self,
        *,
        platform_base_url: str | None,
        call_import_id: str,
        evaluation_id: str,
        conversation_id: str | None,
        evaluation_row_id: str | None = None,
    ) -> str | None:
        base = (platform_base_url or "").strip().rstrip("/")
        if not base:
            return None
        conv = str(conversation_id or "").strip()
        if not conv and not evaluation_row_id:
            return None
        path = (
            f"{base}/call-imports/{call_import_id}/evaluations/{evaluation_id}"
        )
        if conv:
            return f"{path}?conversation_id={quote(conv, safe='')}"
        return f"{path}?row_id={quote(str(evaluation_row_id), safe='')}"

    def _metric_cluster_evidence_html(
        self,
        evidence: dict[str, Any],
        *,
        platform_base_url: str | None,
        call_import_id: str,
        evaluation_id: str,
    ) -> str:
        parts: list[str] = []
        turns = evidence.get("turns")
        if isinstance(turns, list) and turns:
            for turn in turns[:4]:
                if not isinstance(turn, dict):
                    continue
                speaker = html.escape(str(turn.get("speaker") or "User"))
                text = html.escape(str(turn.get("text") or ""))
                if text:
                    parts.append(f"<p><strong>{speaker}:</strong> {text}</p>")
        quote = str(evidence.get("quote") or "").strip()
        if quote and not parts:
            parts.append(f"<p>{html.escape(quote)}</p>")
        conv_id = str(evidence.get("conversation_id") or "").strip()
        row_id = str(evidence.get("evaluation_row_id") or "").strip()
        href = self._evaluation_call_deep_link(
            platform_base_url=platform_base_url,
            call_import_id=call_import_id,
            evaluation_id=evaluation_id,
            conversation_id=conv_id or None,
            evaluation_row_id=row_id or None,
        )
        if href and conv_id:
            parts.append(
                f'<p class="insight-evidence-id"><a href="{html.escape(href)}">'
                f"{html.escape(conv_id)}</a></p>"
            )
        elif conv_id:
            parts.append(
                f'<p class="insight-evidence-id">{html.escape(conv_id)}</p>'
            )
        if not parts:
            return "<p class='empty-bars'>No example call recorded.</p>"
        return "".join(parts)

    def _failure_diagnostics_rca_executive_html(
        self,
        rca_summary: dict[str, Any],
    ) -> str:
        if not isinstance(rca_summary, dict) or not rca_summary:
            return ""
        total_clusters = int(rca_summary.get("total_clusters") or 0)
        total_instances = int(rca_summary.get("total_clustered_instances") or 0)
        total_flagged = int(rca_summary.get("total_flagged_instances") or 0)
        analysed = int(rca_summary.get("analysed_calls") or 0)

        def _pattern_rows() -> str:
            rows_raw = rca_summary.get("repeated_patterns")
            if not isinstance(rows_raw, list):
                return ""
            body: list[str] = []
            max_share = 0.0
            parsed: list[tuple[dict[str, Any], float]] = []
            for row in rows_raw:
                if not isinstance(row, dict):
                    continue
                share = float(row.get("evidence_share_pct") or 0.0)
                parsed.append((row, share))
                max_share = max(max_share, share)
            scale = max(max_share, 1.0)
            for row, share in parsed:
                name = str(row.get("metric_name") or "").strip().upper()
                patterns = str(row.get("top_rca_patterns") or "—").strip()
                calls = int(row.get("evidence_calls") or 0)
                width = min(100.0, (share / scale) * 100.0)
                body.append(
                    f"""
                    <tr>
                      <td class="fd-rca-col-finding">
                        <strong>{html.escape(name)}</strong>
                        <div class="fd-finding-sub">Top RCA patterns: {html.escape(patterns)}</div>
                      </td>
                      <td class="fd-rca-col-pct">{share:.1f}%</td>
                      <td class="fd-rca-col-bar"><div class="fd-rca-track"><div class="fd-rca-fill" style="width: {width:.1f}%"></div></div></td>
                      <td class="fd-rca-col-count">
                        <div class="fd-evidence-primary">{calls:,}</div>
                        <div class="fd-evidence-line">{share:.1f}%</div>
                      </td>
                    </tr>
                    """
                )
            return "".join(body)

        def _hotspot_rows() -> str:
            rows_raw = rca_summary.get("metric_hotspots")
            if not isinstance(rows_raw, list):
                return ""
            body: list[str] = []
            max_rate = 0.0
            parsed: list[tuple[dict[str, Any], float]] = []
            for row in rows_raw:
                if not isinstance(row, dict):
                    continue
                rate = float(row.get("metric_rate_pct") or 0.0)
                parsed.append((row, rate))
                max_rate = max(max_rate, rate)
            scale = max(max_rate, 1.0)
            for row, rate in parsed:
                name = str(row.get("metric_name") or "").strip().upper()
                flagged = int(row.get("flagged_calls") or 0)
                width = min(100.0, (rate / scale) * 100.0)
                body.append(
                    f"""
                    <tr>
                      <td><strong>{html.escape(name)}</strong></td>
                      <td class="fd-rca-col-pct">{rate:.2f}%</td>
                      <td class="fd-rca-col-bar"><div class="fd-rca-track"><div class="fd-rca-fill" style="width: {width:.1f}%"></div></div></td>
                      <td class="fd-rca-col-count">{flagged}</td>
                    </tr>
                    """
                )
            return "".join(body)

        def _prompt_area_rows() -> str:
            rows_raw = rca_summary.get("prompt_areas")
            if not isinstance(rows_raw, list):
                return ""
            return "".join(
                f"""
                <tr>
                  <td>{html.escape(str(row.get('label') or ''))}</td>
                  <td class="fd-col-num">{float(row.get('share_pct') or 0):.1f}%</td>
                </tr>
                """
                for row in rows_raw[:5]
                if isinstance(row, dict)
            )

        def _mini_table(
            title: str,
            headers: tuple[str, ...],
            body_html: str,
        ) -> str:
            if not body_html:
                return ""
            head_cells = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
            return f"""
              <div class="fd-rca-mini">
                <div class="subhead">{html.escape(title)}</div>
                <table class="insight-table fd-rca-mini-table">
                  <thead><tr>{head_cells}</tr></thead>
                  <tbody>{body_html}</tbody>
                </table>
              </div>
            """

        patterns_body = _pattern_rows()
        hotspots_body = _hotspot_rows()
        prompt_body = _prompt_area_rows()
        top_pattern = ""
        patterns_raw = rca_summary.get("repeated_patterns")
        if isinstance(patterns_raw, list) and patterns_raw:
            first = patterns_raw[0]
            if isinstance(first, dict):
                top_pattern = str(first.get("metric_name") or "").strip()

        top_hotspot = ""
        top_hotspot_rate = 0.0
        hotspots_raw = rca_summary.get("metric_hotspots")
        if isinstance(hotspots_raw, list) and hotspots_raw:
            first_h = hotspots_raw[0]
            if isinstance(first_h, dict):
                top_hotspot = str(first_h.get("metric_name") or "").strip()
                top_hotspot_rate = float(first_h.get("metric_rate_pct") or 0.0)

        pattern_interpretation = ""
        if top_pattern and patterns_body:
            pattern_interpretation = f"""
              <div class="insight-callout insight-observation-box fd-rca-interpretation">
                <div class="insight-callout-label">Executive interpretation</div>
                <p>These rows group repeated RCA failure patterns by metric so the same
                metric is not repeated across multiple rows. The largest group is
                <strong>{html.escape(top_pattern)}</strong>; reproduce that pattern first using
                the linked sample calls in the cluster detail below.</p>
              </div>
            """

        hotspot_interpretation = ""
        if top_hotspot and hotspots_body:
            hotspot_interpretation = f"""
              <div class="insight-callout insight-observation-box fd-rca-interpretation">
                <div class="insight-callout-label">Executive interpretation</div>
                <p>Across {analysed:,} analysed calls, <strong>{html.escape(top_hotspot)}</strong>
                has the highest metric rate at {top_hotspot_rate:.2f}%.</p>
              </div>
            """

        repeated_section = ""
        if patterns_body:
            repeated_section = f"""
              <div class="fd-rca-block">
                <h3>4.2 Repeated failure patterns</h3>
                <p class="method fd-rca-base">
                  Base: {total_clusters} RCA clusters generated from {total_instances:,}
                  clustered rationale-backed metric-call instances. Selected metrics contain
                  {total_flagged:,} total flagged metric-call instances across {analysed:,}
                  analysed calls.
                </p>
                <div class="fd-rca-patterns-wrap">
                <table class="insight-table fd-rca-table fd-rca-patterns-table">
                  <thead>
                    <tr>
                      <th class="fd-rca-col-finding">Finding</th>
                      <th class="fd-rca-col-pct">Evidence share</th>
                      <th class="fd-rca-col-bar">Distribution</th>
                      <th class="fd-rca-col-count">Evidence calls</th>
                    </tr>
                  </thead>
                  <tbody>{patterns_body}</tbody>
                </table>
                </div>
                {pattern_interpretation}
              </div>
            """

        hotspot_section = ""
        if hotspots_body:
            hotspot_section = f"""
              <div class="fd-rca-block">
                <h3>4.3 Metric hotspots</h3>
                <p class="method fd-rca-base">
                  Base: selected metric flags across {analysed:,} analysed calls.
                </p>
                <table class="insight-table fd-rca-table fd-rca-hotspots-table">
                  <thead>
                    <tr>
                      <th>Finding</th>
                      <th>Metric rate</th>
                      <th>Distribution</th>
                      <th>Flagged calls</th>
                    </tr>
                  </thead>
                  <tbody>{hotspots_body}</tbody>
                </table>
                {hotspot_interpretation}
              </div>
            """

        summary_section = ""
        if prompt_body or patterns_body or hotspots_body:
            mini_patterns = _mini_table(
                "Repeated patterns",
                ("Pattern", "%"),
                "".join(
                    f"""
                    <tr>
                      <td>{html.escape(str(r.get('metric_name') or ''))}</td>
                      <td class="fd-col-num">{float(r.get('evidence_share_pct') or 0):.1f}%</td>
                    </tr>
                    """
                    for r in (patterns_raw or [])[:5]
                    if isinstance(r, dict)
                )
                if isinstance(patterns_raw, list)
                else "",
            )
            hotspots_raw = rca_summary.get("metric_hotspots")
            mini_hotspots = _mini_table(
                "Metric hotspots",
                ("Metric", "%"),
                "".join(
                    f"""
                    <tr>
                      <td>{html.escape(str(r.get('metric_name') or ''))}</td>
                      <td class="fd-col-num">{float(r.get('metric_rate_pct') or 0):.2f}%</td>
                    </tr>
                    """
                    for r in (hotspots_raw or [])[:5]
                    if isinstance(r, dict)
                )
                if isinstance(hotspots_raw, list)
                else "",
            )
            summary_section = f"""
              <div class="fd-rca-block">
                <h3>4.4 RCA data summary</h3>
                <div class="fd-rca-summary-grid">
                  <div class="fd-rca-prompt-col">
                    <div class="subhead">Prompt areas to inspect</div>
                    <table class="insight-table fd-rca-mini-table">
                      <thead><tr><th>Area</th><th>%</th></tr></thead>
                      <tbody>{prompt_body}</tbody>
                    </table>
                  </div>
                  <div class="fd-rca-twocol">
                    {mini_patterns}
                    {mini_hotspots}
                  </div>
                </div>
              </div>
            """

        return repeated_section + hotspot_section + summary_section

    def _generated_user_insight_evidence_html(self, evidence: dict[str, Any]) -> str:
        parts: list[str] = []
        turns = evidence.get("turns")
        if isinstance(turns, list) and turns:
            for turn in turns[:4]:
                if not isinstance(turn, dict):
                    continue
                speaker = html.escape(str(turn.get("speaker") or "User"))
                text = html.escape(str(turn.get("text") or ""))
                if text:
                    parts.append(f"<p><strong>{speaker}:</strong> {text}</p>")
        quote = str(evidence.get("quote") or "").strip()
        if quote and not parts:
            parts.append(f"<p><strong>User:</strong> {html.escape(quote)}</p>")
        conv_id = str(evidence.get("conversation_id") or "").strip()
        if conv_id:
            parts.append(
                f'<p class="insight-evidence-id">{html.escape(conv_id)}</p>'
            )
        return "".join(parts)

    def _generated_user_insights_overview_html(
        self,
        insights: list[dict[str, Any]],
        overview: str | None,
    ) -> str:
        text = (overview or "").strip()
        if not text and insights:
            parts = [
                f"{str(item.get('title') or '').strip()}: "
                f"{str(item.get('observation') or '').strip()}"
                for item in insights
                if isinstance(item, dict)
                and str(item.get("observation") or "").strip()
            ]
            text = " ".join(parts[:3]).strip()
        if not text:
            return ""
        return f"""
            <div class="insight-overview-box">
              <div class="insight-overview-label">Overview</div>
              <p>{html.escape(_clamp_prose_to_sentences(text))}</p>
            </div>
            """

    def _metric_cluster_table_html(self, clusters: list[dict[str, Any]]) -> str:
        if not clusters:
            return "<p class='empty-bars'>No clusters identified.</p>"
        rows = []
        for cluster in clusters[:12]:
            if not isinstance(cluster, dict):
                continue
            label = str(cluster.get("label") or "").strip()
            if not label:
                continue
            gap = str(cluster.get("gap_label") or "").strip()
            count = int(cluster.get("count") or 0)
            pct = float(cluster.get("share_pct") or 0.0)
            rows.append(
                f"""
                <tr>
                  <td>{html.escape(label)}</td>
                  <td><span class="gap-badge">{html.escape(gap)}</span></td>
                  <td>{pct:.1f}%</td>
                  <td><div class="insight-track"><div class="insight-fill" style="width: {pct:.1f}%"></div></div></td>
                  <td>{count}</td>
                </tr>
                """
            )
        if not rows:
            return "<p class='empty-bars'>No clusters identified.</p>"
        return (
            "<table class='insight-table'>"
            "<thead><tr><th>Cluster</th><th>Gap label</th><th>Share</th>"
            "<th>Distribution</th><th>Calls</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    def _top_metric_clusters(
        self, clusters: list[dict[str, Any]], *, limit: int = 5
    ) -> list[dict[str, Any]]:
        ordered = sorted(
            [c for c in clusters if isinstance(c, dict)],
            key=lambda c: (-max(0, int(c.get("count") or 0)), str(c.get("label") or "")),
        )
        return ordered[:limit]

    def _metric_cluster_level1_table_html(
        self,
        clusters: list[dict[str, Any]],
        flagged_count: int,
        *,
        limit: int = 5,
    ) -> str:
        """Segregated Level-1 cluster table for one metric (replaces running bar stack)."""
        clusters = self._top_metric_clusters(clusters, limit=limit)
        if not clusters:
            return "<p class='empty-bars'>No clusters identified.</p>"
        total_flagged = max(0, int(flagged_count or 0))
        categorized_calls = sum(
            max(0, int(cluster.get("count") or 0)) for cluster in clusters
        )
        body_rows: list[str] = []
        for index, cluster in enumerate(clusters, start=1):
            if not isinstance(cluster, dict):
                continue
            label = str(cluster.get("label") or "").strip()
            if not label:
                continue
            gap = str(cluster.get("gap_label") or "").strip()
            count = max(0, int(cluster.get("count") or 0))
            pct = (
                min(100.0, (count / total_flagged) * 100.0)
                if total_flagged > 0
                else float(cluster.get("share_pct") or 0.0)
            )
            body_rows.append(
                f"""
                <tr>
                  <td class="fd-num">{index}</td>
                  <td>{html.escape(label)}</td>
                  <td><span class="gap-badge">{html.escape(gap)}</span></td>
                  <td>{count}</td>
                  <td>{pct:.1f}%</td>
                  <td><div class="insight-track"><div class="insight-fill" style="width: {pct:.1f}%"></div></div></td>
                </tr>
                """
            )
        if not body_rows:
            return "<p class='empty-bars'>No clusters identified.</p>"
        return f"""
            <p class="fd-breakdown-caption">
              {categorized_calls} categorized / {total_flagged} flagged calls for this metric
            </p>
            <table class="insight-table fd-level1-table">
              <colgroup>
                <col class="fd-col-index" />
                <col class="fd-col-cluster" />
                <col class="fd-col-gap" />
                <col class="fd-col-num" />
                <col class="fd-col-share" />
                <col class="fd-col-bar" />
              </colgroup>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Cluster</th>
                  <th>Gap</th>
                  <th>Calls</th>
                  <th>Share</th>
                  <th>Distribution</th>
                </tr>
              </thead>
              <tbody>{''.join(body_rows)}</tbody>
            </table>
        """

    @staticmethod
    def _fd_cluster_preview_cell_html(
        labels: list[str],
        *,
        max_items: int = 3,
    ) -> str:
        """Bulleted preview cell that wraps inside fixed-width PDF tables."""
        cleaned = [label.strip() for label in labels if label and label.strip()]
        if not cleaned:
            return "—"
        items = cleaned[:max_items]
        extra = ""
        if len(cleaned) > max_items:
            extra = (
                f'<li class="fd-preview-more">+{len(cleaned) - max_items} more</li>'
            )
        list_items = "".join(
            f"<li>{html.escape(label)}</li>" for label in items
        )
        return f'<ul class="fd-preview-list">{list_items}{extra}</ul>'

    def _failure_diagnostics_summary_table_html(
        self,
        groups: list[dict[str, Any]],
        discovered: list[dict[str, Any]],
    ) -> str:
        """Structured cross-metric summary (replaces semicolon-separated overview prose)."""
        rows: list[str] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            metric_name = str(group.get("metric_name") or "Metric").strip()
            flagged = max(0, int(group.get("flagged_count") or 0))
            clusters_raw = group.get("clusters")
            clusters = (
                [c for c in clusters_raw if isinstance(c, dict)]
                if isinstance(clusters_raw, list)
                else []
            )
            top_labels = [
                str(c.get("label") or "").strip()
                for c in clusters
                if isinstance(c, dict) and str(c.get("label") or "").strip()
            ]
            preview_cell = self._fd_cluster_preview_cell_html(top_labels)
            rows.append(
                f"""
                <tr>
                  <td class="fd-col-metric">{html.escape(metric_name)}</td>
                  <td class="fd-col-num">{len(clusters)}</td>
                  <td class="fd-col-num">{flagged}</td>
                  <td class="fd-col-preview">{preview_cell}</td>
                </tr>
                """
            )
        if discovered:
            discovered_labels = [
                str(d.get("label") or "").strip()
                for d in discovered
                if isinstance(d, dict) and str(d.get("label") or "").strip()
            ]
            preview_cell = self._fd_cluster_preview_cell_html(discovered_labels)
            rows.append(
                f"""
                <tr class="fd-summary-discovered-row">
                  <td class="fd-col-metric"><strong>Proactive discovery</strong></td>
                  <td class="fd-col-num">{len(discovered)}</td>
                  <td class="fd-col-num">—</td>
                  <td class="fd-col-preview">{preview_cell}</td>
                </tr>
                """
            )
        if not rows:
            return ""
        return f"""
            <div class="insight-overview-box fd-summary-box">
              <div class="insight-overview-label">Overview — metrics at a glance</div>
              <table class="insight-table fd-summary-table">
                <colgroup>
                  <col class="fd-col-metric" />
                  <col class="fd-col-num" />
                  <col class="fd-col-num" />
                  <col class="fd-col-preview" />
                </colgroup>
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Clusters</th>
                    <th>Flagged calls</th>
                    <th>Top clusters (preview)</th>
                  </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
              </table>
            </div>
        """

    def _metric_cluster_sub_bars_html(
        self,
        sub_clusters: list[dict[str, Any]],
        *,
        parent_count: int = 0,
    ) -> str:
        """Horizontal bar chart for Level-2 sub-clusters within a cluster."""
        if not sub_clusters:
            return "<p class='empty-bars'>No Level-2 sub-categories.</p>"
        rows: list[str] = []
        max_pct = 0.0
        parsed: list[tuple[str, int, float]] = []
        for sub in sub_clusters[:10]:
            if not isinstance(sub, dict):
                continue
            label = str(sub.get("label") or "").strip()
            if not label:
                continue
            count = max(0, int(sub.get("count") or 0))
            pct = float(sub.get("share_pct") or 0.0)
            if pct <= 0 and parent_count > 0 and count > 0:
                pct = min(100.0, (count / parent_count) * 100.0)
            parsed.append((label, count, pct))
            max_pct = max(max_pct, pct)
        if not parsed:
            return "<p class='empty-bars'>No Level-2 sub-categories.</p>"
        scale = max(max_pct, 1.0)
        for label, count, pct in parsed:
            width = min(100.0, (pct / scale) * 100.0)
            rows.append(
                f"""
                <div class="dist-row metric-cluster-sub-row">
                  <div class="dist-label">{html.escape(label)}</div>
                  <div class="dist-track">
                    <div class="dist-fill metric-cluster-sub-fill" style="width: {width:.1f}%"></div>
                  </div>
                  <div class="dist-value">{count} · {pct:.1f}%</div>
                </div>
                """
            )
        return f"<div class='metric-cluster-sub-bars'>{''.join(rows)}</div>"

    def _metric_cluster_compact_detail_html(
        self,
        cluster: dict[str, Any],
        *,
        index: int,
        cidx: int,
        failure_reason: str,
        platform_base_url: str | None,
        call_import_id: str,
        evaluation_id: str,
    ) -> str:
        """Lightweight cluster card for PDF (avoids heavy grids that stall WeasyPrint)."""
        label = str(cluster.get("label") or "Cluster").strip()
        gap = str(cluster.get("gap_label") or "").strip().replace("_", " ")
        cluster_count = max(0, int(cluster.get("count") or 0))
        cluster_pct = float(cluster.get("share_pct") or 0.0)
        observation = str(cluster.get("observation") or "").strip()
        if len(observation) > _PDF_FD_OBSERVATION_MAX_CHARS:
            observation = observation[: _PDF_FD_OBSERVATION_MAX_CHARS].rstrip() + "…"
        cluster_failure_reason = str(
            cluster.get("failure_reason") or failure_reason
        ).strip()
        evidence_raw = cluster.get("evidence")
        evidence = evidence_raw if isinstance(evidence_raw, dict) else {}
        example_html = self._metric_cluster_evidence_html(
            evidence,
            platform_base_url=platform_base_url,
            call_import_id=call_import_id,
            evaluation_id=evaluation_id,
        )
        why_flagged = ""
        if cluster_failure_reason:
            why_flagged = f"""
              <p class="fd-why-flagged"><strong>Why flagged:</strong>
              {html.escape(cluster_failure_reason)}</p>
            """
        observation_html = ""
        if observation:
            observation_html = f"""
              <p class="fd-cluster-observation"><strong>Observation:</strong>
              {html.escape(observation)}</p>
            """
        return f"""
            <div class="metric-cluster-detail metric-cluster-detail-compact">
              <div class="metric-cluster-detail-head">
                <h4>4.{index}.{cidx} {html.escape(label)}</h4>
                <span>{html.escape(gap)} · {cluster_count} calls · {cluster_pct:.1f}%</span>
              </div>
              {why_flagged}
              {observation_html}
              <div class="insight-callout insight-evidence-box fd-cluster-example">
                <div class="insight-callout-label">Example call</div>
                {example_html}
              </div>
            </div>
            """

    def _metric_cluster_group_html(
        self,
        group: dict[str, Any],
        index: int,
        *,
        platform_base_url: str | None = None,
        call_import_id: str = "",
        evaluation_id: str = "",
        detail_limit: int = _PDF_FD_MAX_CLUSTER_DETAIL,
    ) -> str:
        metric_name = str(group.get("metric_name") or "Metric").strip()
        flagged = int(group.get("flagged_count") or 0)
        failure_reason = str(group.get("failure_reason") or "").strip()
        clusters_raw = group.get("clusters")
        clusters = self._top_metric_clusters(
            clusters_raw if isinstance(clusters_raw, list) else [],
            limit=5,
        )
        detail_clusters = clusters[: max(0, detail_limit)]
        cluster_blocks = [
            self._metric_cluster_compact_detail_html(
                cluster,
                index=index,
                cidx=cidx,
                failure_reason=failure_reason,
                platform_base_url=platform_base_url,
                call_import_id=call_import_id,
                evaluation_id=evaluation_id,
            )
            for cidx, cluster in enumerate(detail_clusters, start=1)
        ]
        level1_table = self._metric_cluster_level1_table_html(clusters, flagged)
        reason_line = ""
        if failure_reason:
            reason_line = f'<p class="fd-why-flagged"><strong>Why flagged:</strong> {html.escape(failure_reason)}</p>'
        detail_section = ""
        if cluster_blocks:
            detail_section = f"""
              <div class="subhead metric-cluster-detail-section-title">Example clusters (top {len(detail_clusters)})</div>
              <div class="metric-cluster-details">
                {''.join(cluster_blocks)}
              </div>
            """
        return f"""
            <div class="metric-cluster-metric-group">
              <div class="metric-cluster-metric-head">
                <h3>4.{index} {html.escape(metric_name)}</h3>
                <span>{flagged} flagged calls · {len(clusters)} cluster(s)</span>
              </div>
              {reason_line}
              <div class="subhead">Level-1 clusters</div>
              {level1_table}
              {detail_section}
            </div>
            """

    def _cluster_appendix_html(self) -> str:
        return """
              <div class="fd-cluster-appendix">
                <h3>Appendix: What is a cluster?</h3>
                <p class="method">
                  A cluster groups flagged calls that share the same underlying failure
                  theme within a quality metric. Each cluster is labeled with an RCA
                  pattern name and an engineering gap type (such as MISSING, LOGIC_GAP,
                  UNDERSPEC, or EXISTS_NO_TRIGGER). Evidence share is the percentage of
                  all clustered failure instances attributed to that metric&apos;s patterns;
                  evidence calls is the raw count of those instances.
                </p>
              </div>
            """

    def _failure_diagnostics_section_html(
        self,
        metric_clusters: dict[str, Any],
        overview: str | None,
        *,
        platform_base_url: str | None = None,
        call_import_id: str = "",
        evaluation_id: str = "",
    ) -> str:
        groups_raw = metric_clusters.get("groups")
        groups = (
            [g for g in groups_raw if isinstance(g, dict)]
            if isinstance(groups_raw, list)
            else []
        )
        discovered_raw = metric_clusters.get("discovered_problems")
        discovered = (
            [d for d in discovered_raw if isinstance(d, dict)]
            if isinstance(discovered_raw, list)
            else []
        )
        if not groups and not discovered:
            return ""
        overview_markup = self._failure_diagnostics_summary_table_html(
            groups, discovered
        )
        if not overview_markup and (overview or "").strip():
            overview_markup = f"""
              <div class="insight-overview-box fd-summary-box">
                <div class="insight-overview-label">Overview</div>
                <p>{html.escape((overview or "").strip())}</p>
              </div>
            """
        rca_executive = self._failure_diagnostics_rca_executive_html(
            metric_clusters.get("rca_summary")
            if isinstance(metric_clusters.get("rca_summary"), dict)
            else {}
        )
        ordered_groups = sorted(
            groups,
            key=lambda g: -int(g.get("flagged_count") or 0),
        )
        rendered_groups = ordered_groups[:_PDF_FD_MAX_METRIC_GROUPS]
        omitted = len(ordered_groups) - len(rendered_groups)
        group_blocks = [
            self._metric_cluster_group_html(
                group,
                idx,
                platform_base_url=platform_base_url,
                call_import_id=call_import_id,
                evaluation_id=evaluation_id,
            )
            for idx, group in enumerate(rendered_groups, start=1)
        ]
        omitted_note = ""
        if omitted > 0:
            omitted_note = (
                f'<p class="method fd-omitted-metrics">'
                f"{omitted} additional metric(s) with clusters are summarized in "
                f"sections 4.2–4.4 and the overview table; open the evaluation "
                f"Clusters tab for full per-metric detail.</p>"
            )
        discovered_table = self._metric_cluster_table_html(discovered)
        discovered_section = ""
        if discovered:
            discovered_section = f"""
              <div class="fd-discovered-block">
                <div class="metric-cluster-metric-head">
                  <h3>Proactive problem discovery</h3>
                  <span>{len(discovered)} theme(s) · not mapped to standard metrics</span>
                </div>
                {discovered_table}
              </div>
            """
        metrics_body = "".join(group_blocks)
        if not metrics_body and not discovered_section:
            metrics_body = "<p class='empty-bars'>No cluster groups in this run.</p>"
        return f"""
            <section class="failure-diagnostics">
              <div class="failure-diagnostics-intro">
                <h2>04 Failure Diagnostics</h2>
                <p class="method">Per-metric clustering of flagged calls with engineering gap labels (LOGIC_GAP, UNDERSPEC, EXISTS_NO_TRIGGER, MISSING) and Level-2 sub-categories.</p>
                {overview_markup}
              </div>
              {rca_executive}
              {omitted_note}
              <div class="failure-diagnostics-metrics">
                {metrics_body}
                {discovered_section}
              </div>
              {self._cluster_appendix_html()}
            </section>
            """

    def _prompt_improvement_text_block_html(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        return f'<div class="prompt-change-text">{html.escape(cleaned)}</div>'

    def _prompt_improvement_change_markup_html(self, item: dict[str, Any]) -> str:
        change_type = _prompt_improvement_change_type(item)
        anchor_excerpt = str(item.get("anchor_excerpt") or "").strip()
        suggested_text = str(item.get("suggested_text") or "").strip()

        if change_type == "edit" and anchor_excerpt:
            return f"""
              <div class="prompt-change-grid">
                <div class="prompt-change-box prompt-change-before">
                  <div class="prompt-change-label">Current prompt (being changed)</div>
                  {self._prompt_improvement_text_block_html(anchor_excerpt)}
                </div>
                <div class="prompt-change-box prompt-change-after">
                  <div class="prompt-change-label">Suggested replacement</div>
                  {self._prompt_improvement_text_block_html(suggested_text)}
                </div>
              </div>
            """
        if suggested_text:
            return f"""
              <div class="prompt-change-box prompt-change-add">
                <div class="prompt-change-label">Suggested prompt addition</div>
                {self._prompt_improvement_text_block_html(suggested_text)}
              </div>
            """
        return ""

    def _prompt_improvements_section_html(
        self,
        prompt_improvements: dict[str, Any],
    ) -> str:
        suggestions_raw = prompt_improvements.get("suggestions")
        suggestions = (
            [s for s in suggestions_raw if isinstance(s, dict)]
            if isinstance(suggestions_raw, list)
            else []
        )
        suggestions = _sort_prompt_improvement_suggestions(suggestions)[
            :_PDF_PROMPT_IMPROVEMENTS_MAX
        ]
        if not suggestions:
            return ""
        agent_name = str(prompt_improvements.get("imported_agent_name") or "Imported agent")
        overview = str(prompt_improvements.get("overview") or "").strip()
        overview_markup = ""
        if overview:
            overview_markup = f"""
              <div class="insight-overview-box fd-summary-box">
                <div class="insight-overview-label">Overview</div>
                <p>{html.escape(overview)}</p>
              </div>
            """
        blocks: list[str] = []
        for idx, item in enumerate(suggestions, start=1):
            metric_name = html.escape(str(item.get("metric_name") or "Metric"))
            cluster_label = html.escape(str(item.get("cluster_label") or "Cluster"))
            gap_label = html.escape(str(item.get("gap_label") or ""))
            priority = html.escape(str(item.get("priority") or "medium"))
            share_pct = float(item.get("share_pct") or 0)
            target_section = html.escape(str(item.get("target_section") or ""))
            flow_node_label = html.escape(str(item.get("flow_node_label") or ""))
            current_gap = html.escape(str(item.get("current_gap") or ""))
            rationale = html.escape(str(item.get("rationale") or ""))
            change_type = _prompt_improvement_change_type(item)
            change_label = "Edit existing" if change_type == "edit" else "New addition"
            change_badge_class = (
                "prompt-change-badge-edit"
                if change_type == "edit"
                else "prompt-change-badge-add"
            )
            change_markup = self._prompt_improvement_change_markup_html(item)
            blocks.append(
                f"""
                <article class="metric-cluster-group prompt-improvement-card">
                  <div class="metric-cluster-metric-head">
                    <h3>{idx}. {metric_name} · {cluster_label}</h3>
                    <span class="prompt-improvement-meta">
                      <span class="prompt-change-badge {change_badge_class}">{change_label}</span>
                      {gap_label} · {priority} priority · {share_pct:.1f}% share
                    </span>
                  </div>
                  {f'<p class="method"><strong>Target section:</strong> {target_section}</p>' if target_section else ''}
                  {f'<p class="method"><strong>Agent logic node:</strong> {flow_node_label}</p>' if flow_node_label else ''}
                  {f'<p class="method"><strong>Current gap:</strong> {current_gap}</p>' if current_gap else ''}
                  {change_markup}
                  {f'<p class="method prompt-improvement-rationale"><strong>Rationale:</strong> {rationale}</p>' if rationale else ''}
                </article>
                """
            )
        return f"""
            <section class="prompt-improvements">
              <div class="failure-diagnostics-intro">
                <h2>05 Prompt Improvement Recommendations</h2>
                <p class="method">Top {_PDF_PROMPT_IMPROVEMENTS_MAX} recommended prompt changes for <strong>{html.escape(agent_name)}</strong>, aligned with the Visualizations → Prompt / Agent Improvements view.</p>
                {overview_markup}
              </div>
              {''.join(blocks)}
            </section>
            """

    def _generated_user_insight_block_html(
        self, insight: dict[str, Any], index: int
    ) -> str:
        title = str(insight.get("title") or "User Insight").strip()
        observation = str(insight.get("observation") or "").strip()
        categories = insight.get("categories")
        cat_list = categories if isinstance(categories, list) else []
        evidence_raw = insight.get("evidence")
        evidence = evidence_raw if isinstance(evidence_raw, dict) else {}

        observation_box = ""
        if observation:
            observation_box = f"""
              <div class="insight-callout insight-observation-box">
                <div class="insight-callout-label">Observation</div>
                <p>{html.escape(observation)}</p>
              </div>
            """

        evidence_html = self._generated_user_insight_evidence_html(evidence)
        evidence_box = ""
        if evidence_html:
            evidence_box = f"""
              <div class="insight-callout insight-evidence-box">
                <div class="insight-callout-label">Example</div>
                {evidence_html}
              </div>
            """

        side_markup = ""
        if observation_box or evidence_box:
            side_markup = f"""
              <div class="insight-sidecol">
                {observation_box}
                {evidence_box}
              </div>
            """

        return f"""
                <div class="insight-block">
                  <div class="insight-heading">
                    <h3>3.{index} {html.escape(title)}</h3>
                  </div>
                  <div class="insight-body">
                    <div class="insight-table-col">
                      {self._generated_insight_distribution_table_html(cat_list)}
                    </div>
                    {side_markup}
                  </div>
                </div>
                """

    def _top_metric_percentages_html(
        self,
        quality_metrics: list[MetricReportSummary],
        *,
        limit: int = 5,
    ) -> str:
        ranked = self._top_quality_metric_summaries(quality_metrics, limit=limit)
        if not ranked:
            return ""
        cards = []
        for summary in ranked:
            label = html.escape(summary.name.upper())
            value = html.escape(self._primary_metric_label(summary))
            cards.append(
                f"""
                <div class="audit-stat-card">
                  <div class="audit-stat-rule"></div>
                  <div class="audit-stat-label">{label}</div>
                  <div class="audit-stat-value">{value}</div>
                </div>
                """
            )
        return f'<div class="audit-stat-strip">{"".join(cards)}</div>'

    def _top_quality_metric_summaries(
        self,
        quality_metrics: list[MetricReportSummary],
        *,
        limit: int = 5,
    ) -> list[MetricReportSummary]:
        return sorted(
            quality_metrics,
            key=lambda summary: self._primary_metric_percent(summary),
            reverse=True,
        )[:limit]

    def _period_delta_values(self, detail: str) -> tuple[float, float] | None:
        values = [float(match) for match in re.findall(r"(\d+(?:\.\d+)?)%", detail)]
        if len(values) < 2:
            return None
        current_pct, previous_pct = values[0], values[1]
        return current_pct, previous_pct

    def _top_metric_delta_line_graphs_html(
        self,
        quality_metrics: list[MetricReportSummary],
        *,
        limit: int = 5,
    ) -> str:
        ranked = self._top_quality_metric_summaries(quality_metrics, limit=limit)
        if not ranked:
            return ""
        cards = []
        for summary in ranked:
            label = summary.weekly_delta_label or "No previous-week baseline"
            detail = summary.weekly_delta_detail or ""
            why = (summary.weekly_delta_why or "").strip()
            reason = (
                _clamp_prose_to_sentences(why, max_sentences=2)
                if why
                else "Reason not available for this comparison."
            )
            current_previous = self._period_delta_values(detail)
            tone = "flat"
            arrow = ""
            direction_label = self._metric_direction_label(summary)
            if current_previous is not None:
                current_pct, previous_pct = current_previous
                delta = current_pct - previous_pct
                tone = "bad" if delta > 0 else "good" if delta < 0 else "flat"
                arrow = " ▲" if delta > 0 else " ▼" if delta < 0 else " ━"
                chart_markup = self._delta_sparkline_svg(
                    previous_pct,
                    current_pct,
                    tone=tone,
                    previous_label="Last",
                    current_label="Current",
                    show_pct_labels=True,
                )
            else:
                chart_markup = '<div class="audit-delta-empty">No comparable line data</div>'
            cards.append(
                f"""
                <article class="audit-delta-card delta-{tone}">
                  <div class="audit-delta-head">
                    <div class="audit-delta-head-main">
                      <span>{html.escape(summary.name.upper())}</span>
                      <small class="audit-delta-direction">{html.escape(direction_label)}</small>
                    </div>
                    <strong>{html.escape(label)}{arrow}</strong>
                  </div>
                  <div class="audit-delta-chart">{chart_markup}</div>
                  <p class="audit-delta-reason">{html.escape(reason)}</p>
                </article>
                """
            )
        return f"""
          <div class="audit-delta-panel">
            <div class="audit-delta-title">Top metric delta vs last week</div>
            <div class="audit-delta-grid">{"".join(cards)}</div>
          </div>
        """

    def _audit_summary_html(self, text: str) -> str:
        compact = _clamp_prose_to_sentences(text)
        if not compact:
            return ""
        return f"<p>{html.escape(compact)}</p>"

    def _short_business_meaning(self, summary: MetricReportSummary) -> str:
        description = (summary.description or "").strip()
        if not description:
            return "No business interpretation is available for this metric yet."
        sentences = re.split(r"(?<=[.!?])\s+", description)
        compact = " ".join(sentence.strip() for sentence in sentences[:2] if sentence.strip())
        if not compact:
            compact = description
        if len(compact) > 240:
            compact = compact[:237].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
        return compact

    def _sparkline_palette(self, tone: str) -> dict[str, str]:
        palettes = {
            "good": {
                "line": "#047857",
                "area": "#dcfce7",
                "dot": "#047857",
                "label": "#94a3b8",
            },
            "bad": {
                "line": "#b42318",
                "area": "#fee2e2",
                "dot": "#b42318",
                "label": "#94a3b8",
            },
            "flat": {
                "line": "#475569",
                "area": "#e2e8f0",
                "dot": "#475569",
                "label": "#94a3b8",
            },
        }
        return palettes.get(tone, palettes["flat"])

    def _delta_sparkline_svg(
        self,
        previous_pct: float,
        current_pct: float,
        *,
        tone: str = "flat",
        previous_label: str = "Prev",
        current_label: str = "Current",
        show_pct_labels: bool = False,
    ) -> str:
        colors = self._sparkline_palette(tone)
        width = 118
        height = 50 if show_pct_labels else 44
        padding_x = 8
        padding_y = 8
        chart_width = width - (padding_x * 2)
        label_block_height = 14 if show_pct_labels else 10
        chart_height = height - label_block_height - 6
        max_value = max(previous_pct, current_pct, 1.0)
        min_value = min(previous_pct, current_pct, 0.0)
        span = max(max_value - min_value, 1.0)

        def point_x(index: int) -> float:
            if index <= 0:
                return float(padding_x)
            return float(padding_x + chart_width)

        def point_y(value: float) -> float:
            normalized = (value - min_value) / span
            return float(padding_y + chart_height - (normalized * chart_height))

        x1, y1 = point_x(0), point_y(previous_pct)
        x2, y2 = point_x(1), point_y(current_pct)
        area_points = (
            f"{x1},{padding_y + chart_height} "
            f"{x1},{y1} "
            f"{x2},{y2} "
            f"{x2},{padding_y + chart_height}"
        )
        axis_y = height - (10 if show_pct_labels else 3)
        pct_y = height - 2
        pct_markup = ""
        if show_pct_labels:
            pct_markup = f"""
            <text x="{padding_x}" y="{pct_y}" fill="{colors['label']}" font-size="5" font-family="Helvetica, Arial, sans-serif">{previous_pct:.1f}%</text>
            <text x="{width - padding_x}" y="{pct_y}" text-anchor="end" fill="{colors['label']}" font-size="5" font-family="Helvetica, Arial, sans-serif">{current_pct:.1f}%</text>
            """
        return f"""
          <svg class="metric-sparkline" viewBox="0 0 {width} {height}" width="{width}" height="{height}" aria-hidden="true">
            <polygon points="{area_points}" fill="{colors['area']}" stroke="none" />
            <polyline points="{x1:.1f},{y1:.1f} {x2:.1f},{y2:.1f}" fill="none" stroke="{colors['line']}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
            <circle cx="{x1:.1f}" cy="{y1:.1f}" r="2.2" fill="{colors['dot']}" />
            <circle cx="{x2:.1f}" cy="{y2:.1f}" r="2.2" fill="{colors['dot']}" />
            <text x="{padding_x}" y="{axis_y}" fill="{colors['label']}" font-size="4" font-family="Helvetica, Arial, sans-serif">{html.escape(previous_label)}</text>
            <text x="{width - padding_x}" y="{axis_y}" text-anchor="end" fill="{colors['label']}" font-size="4" font-family="Helvetica, Arial, sans-serif">{html.escape(current_label)}</text>
            {pct_markup}
          </svg>
        """

    def _compact_weekly_delta_html(self, summary: MetricReportSummary) -> tuple[str, str]:
        label = summary.weekly_delta_label or "No previous-week baseline"
        detail = summary.weekly_delta_detail or ""
        values = [float(match) for match in re.findall(r"(\d+(?:\.\d+)?)%", detail)]
        sparkline = ""
        if len(values) >= 2:
            current_pct, previous_pct = values[0], values[1]
            delta = current_pct - previous_pct
            tone = "bad" if delta > 0 else "good" if delta < 0 else "flat"
            arrow = "▲" if delta > 0 else "▼" if delta < 0 else "━"
            sparkline = self._delta_sparkline_svg(
                previous_pct,
                current_pct,
                tone=tone,
            )
            delta_markup = f"""
              <div class="metric-compact-delta delta-{tone}">
                <div class="metric-compact-delta-row">
                  <span>vs last week</span>
                  <strong>{html.escape(label)} {arrow}</strong>
                  <small>{previous_pct:.2f}%</small>
                </div>
              </div>
            """
            return delta_markup, sparkline
        delta_markup = f"""
          <div class="metric-compact-delta delta-flat">
            <div class="metric-compact-delta-row">
              <span>vs last week</span>
              <strong>{html.escape(label)}</strong>
            </div>
            <small class="metric-compact-delta-detail">{html.escape(detail)}</small>
          </div>
        """
        return delta_markup, sparkline

    def _compact_metric_card_html(
        self,
        summary: MetricReportSummary,
        *,
        business_meaning: str,
        include_weekly_delta: bool,
        accuracy: str,
        include_sparkline: bool = True,
        show_accuracy: bool = True,
    ) -> str:
        delta_markup = ""
        sparkline_markup = ""
        if include_weekly_delta:
            delta_markup, sparkline_markup = self._compact_weekly_delta_html(summary)
            if not include_sparkline:
                sparkline_markup = ""
        meta_text = f"{summary.flagged_count} of {summary.evaluated_count}"
        if show_accuracy:
            meta_text = f"{meta_text} · acc {accuracy}"
        return f"""
          <article class="metric metric-compact">
            <div class="metric-compact-head">
              <div class="metric-title">{html.escape(summary.name)}</div>
              <span class="metric-compact-status"></span>
            </div>
            <div class="metric-compact-hero">
              <div class="metric-compact-main">
                <div class="metric-percent">{html.escape(self._primary_metric_label(summary))}</div>
                {delta_markup}
              </div>
              <div class="metric-compact-sparkline">{sparkline_markup}</div>
            </div>
            <p class="meaning metric-compact-meaning">{html.escape(business_meaning)}</p>
            <div class="metric-compact-meta">
              {html.escape(meta_text)}
            </div>
          </article>
        """

    def _delta_chart_html(
        self,
        summary: MetricReportSummary,
        benchmark_context: dict[str, str] | None = None,
    ) -> str:
        label = summary.weekly_delta_label or "No previous-week baseline"
        detail = summary.weekly_delta_detail or ""
        values = [float(match) for match in re.findall(r"(\d+(?:\.\d+)?)%", detail)]
        if len(values) >= 2:
            current_pct, previous_pct = values[0], values[1]
            delta = current_pct - previous_pct
            tone = "bad" if delta > 0 else "good" if delta < 0 else "flat"
            arrow = "▲" if delta > 0 else "▼" if delta < 0 else "━"
            benchmark_markup = ""
            if benchmark_context:
                benchmark_markup = (
                    '<div class="delta-benchmark">'
                    f'Benchmark: {html.escape(benchmark_context.get("dataset", "Unknown dataset"))} · '
                    f'Evaluation {html.escape(benchmark_context.get("evaluation", ""))} · '
                    f'{html.escape(benchmark_context.get("period", ""))}'
                    "</div>"
                )
            return f"""
              <div class="delta-card delta-{tone}">
                <div class="delta-head">
                  <span>Week-over-week</span>
                  <strong>{html.escape(label)} {arrow}</strong>
                </div>
                <div class="delta-bars">
                  <div class="delta-row">
                    <span>Last week</span>
                    <div class="delta-track"><div class="delta-fill delta-fill-prev" style="width: {max(0.0, min(previous_pct, 100.0)):.1f}%"></div></div>
                    <b>{previous_pct:.1f}%</b>
                  </div>
                  <div class="delta-row">
                    <span>This week</span>
                    <div class="delta-track"><div class="delta-fill delta-fill-current" style="width: {max(0.0, min(current_pct, 100.0)):.1f}%"></div></div>
                    <b>{current_pct:.1f}%</b>
                  </div>
                </div>
                {benchmark_markup}
              </div>
            """
        return f"""
          <div class="delta-card delta-flat">
            <div class="delta-head">
              <span>Week-over-week</span>
              <strong>{html.escape(label)}</strong>
            </div>
            <small>{html.escape(detail)}</small>
          </div>
        """

    def _render_html(self, payload: dict[str, Any]) -> str:
        metrics: list[MetricReportSummary] = payload["metrics"]
        report_config = payload.get("report_config") if isinstance(payload.get("report_config"), dict) else {}
        sections = report_config.get("sections") if isinstance(report_config.get("sections"), dict) else {}
        show_audit_summary = sections.get("audit_summary", True)
        show_quality_panel = sections.get("quality_panel", True)
        show_user_insights = sections.get("user_insights", True)
        show_design_notes = sections.get("design_notes", True)
        show_failure_diagnostics = sections.get("failure_diagnostics", True)
        show_prompt_improvements = sections.get("prompt_improvements", True)
        show_methodology = sections.get("methodology", True)
        narrative = payload.get("narrative") if isinstance(payload.get("narrative"), dict) else {}
        observations = narrative.get("observations") if isinstance(narrative.get("observations"), dict) else {}
        evidence = narrative.get("evidence") if isinstance(narrative.get("evidence"), dict) else {}
        design_notes = narrative.get("design_notes") if isinstance(narrative.get("design_notes"), list) else []
        insight_config = {}
        for item in report_config.get("insights", []) if isinstance(report_config.get("insights"), list) else []:
            if isinstance(item, dict) and item.get("metric_id"):
                insight_config[str(item["metric_id"])] = item
        metric_insights = (
            payload.get("metric_insights")
            if isinstance(payload.get("metric_insights"), dict)
            else {}
        )
        quality_metrics = [m for m in metrics if not m.is_business_metric]
        business_metrics = [m for m in metrics if m.is_business_metric]
        if not quality_metrics:
            quality_metrics = metrics
        logo_uris = payload.get("logo_data_uris") or {}
        internal_logo_uri = ""
        external_logo_uri = ""
        if isinstance(logo_uris, dict):
            internal_logo_uri = str(logo_uris.get("internal") or "")
            external_logo_uri = str(logo_uris.get("external") or "")
        elif isinstance(logo_uris, list):
            valid_logo_uris = [uri for uri in logo_uris if isinstance(uri, str) and uri]
            internal_logo_uri = valid_logo_uris[0] if valid_logo_uris else ""
            external_logo_uri = valid_logo_uris[1] if len(valid_logo_uris) > 1 else ""
        logo_markup = ""
        if internal_logo_uri or external_logo_uri:
            internal_img = (
                f'<img src="{internal_logo_uri}" alt="Internal brand" class="brand-logo" />'
                if internal_logo_uri
                else '<span class="brand-placeholder"></span>'
            )
            external_img = (
                f'<img src="{external_logo_uri}" alt="External vendor brand" class="brand-logo" />'
                if external_logo_uri
                else '<span class="brand-placeholder"></span>'
            )
            logo_markup = (
                '<div class="brand-logo-slot brand-logo-slot-internal">'
                f"{internal_img}</div>"
                '<div class="brand-logo-slot brand-logo-slot-external">'
                f"{external_img}</div>"
            )
        heading_markup = (
            f'<div class="brand-text">{html.escape(payload["custom_heading"])}</div>'
            if payload.get("custom_heading")
            else ""
        )
        brand_header_parts: list[str] = []
        if logo_markup:
            brand_header_parts.append(
                f'<div class="brand-logo-row">{logo_markup}</div>'
            )
        if heading_markup:
            brand_header_parts.append(heading_markup)
        brand_header_markup = (
            f'<div class="brand-header">{"".join(brand_header_parts)}</div>'
            if brand_header_parts
            else ""
        )
        evidence_rows = []
        for summary in metrics:
            for call_id, rationale in summary.rationales[:4]:
                evidence_rows.append(
                    f"""
                    <tr>
                      <td>{html.escape(summary.name)}</td>
                      <td>{html.escape(call_id)}</td>
                      <td>{html.escape(rationale[:500])}</td>
                    </tr>
                    """
                )
        if not evidence_rows:
            evidence_rows.append(
                "<tr><td colspan='3'>No flagged-call rationales were captured for this run.</td></tr>"
            )

        metric_cards_by_group: dict[str, list[str]] = {}
        is_internal = bool(payload.get("internal"))
        include_weekly_delta = bool(payload.get("include_weekly_delta"))
        for summary in quality_metrics:
            business_meaning = (
                str(metric_insights.get(summary.id) or "").strip()
                or self._short_business_meaning(summary)
            )
            accuracy = self._percent(
                summary.evaluated_count, payload["evaluation"].total_rows
            )
            card = self._compact_metric_card_html(
                summary,
                business_meaning=business_meaning,
                include_weekly_delta=include_weekly_delta,
                accuracy=accuracy,
                include_sparkline=not is_internal,
                show_accuracy=not is_internal,
            )
            metric_cards_by_group.setdefault(summary.group_name, []).append(card)

        quality_panel_markup = ""
        if show_quality_panel:
            quality_groups_markup = []
            for group_name, cards in metric_cards_by_group.items():
                cards_markup = (
                    f'<div class="metric-compact-grid">{"".join(cards)}</div>'
                )
                quality_groups_markup.append(
                    f"""
                    <div class="metric-group">
                      <h3 class="metric-group-title">{html.escape(group_name)}</h3>
                      {cards_markup}
                    </div>
                    """
                )
            quality_panel_markup = f"""
            <section>
              <h2>02 Quality Metric Panel</h2>
              {''.join(quality_groups_markup)}
            </section>
            """

        insight_blocks = []
        generated_insights = payload.get("generated_user_insights")
        generated_list = (
            [item for item in generated_insights if isinstance(item, dict)]
            if isinstance(generated_insights, list)
            else []
        )
        if is_internal:
            for index, summary in enumerate(business_metrics, start=1):
                accuracy = self._percent(summary.evaluated_count, payload["evaluation"].total_rows)
                cfg = insight_config.get(summary.id, {})
                show_observation = bool(cfg.get("show_observation", True))
                show_evidence = bool(cfg.get("show_evidence", True))
                observation_text = observations.get(summary.id)
                evidence_item = evidence.get(summary.id)
                if not evidence_item and summary.rationales:
                    evidence_item = {
                        "conversation_id": summary.rationales[0][0],
                        "quote": summary.rationales[0][1],
                    }
                evidence_markup = ""
                if show_evidence and isinstance(evidence_item, dict):
                    evidence_markup = (
                        '<p class="insight-evidence"><strong>Evidence:</strong> '
                        f'{html.escape(str(evidence_item.get("quote") or ""))}'
                        f' <span>{html.escape(str(evidence_item.get("conversation_id") or ""))}</span></p>'
                    )
                observation_markup = (
                    f'<p class="insight-observation"><strong>Observation:</strong> {html.escape(str(observation_text))}</p>'
                    if show_observation and observation_text
                    else ""
                )
                insight_blocks.append(
                    f"""
                    <div class="insight-block">
                      <div class="insight-heading">
                        <h3>3.{index} {html.escape(summary.name)}</h3>
                        <span>{html.escape(summary.name.lower().replace(" ", "-"))}-classifier · acc {html.escape(accuracy)}</span>
                      </div>
                      {self._insight_distribution_table_html(summary)}
                      {observation_markup}
                      {evidence_markup}
                    </div>
                    """
                )
        elif show_user_insights:
            overview_markup = ""
            if generated_list:
                overview_text = payload.get("user_insights_overview")
                overview_markup = self._generated_user_insights_overview_html(
                    generated_list,
                    str(overview_text) if overview_text else None,
                )
            for index, insight in enumerate(generated_list, start=1):
                insight_blocks.append(
                    self._generated_user_insight_block_html(insight, index)
                )
            if not insight_blocks:
                insight_blocks.append(
                    '<p class="method">Generate user insights from the Visualizations '
                    "tab (Generate summary) before including this section.</p>"
                )
            elif overview_markup:
                insight_blocks.insert(0, overview_markup)
        failure_diagnostics_section = ""
        if is_internal and show_failure_diagnostics:
            clusters_payload = payload.get("metric_clusters")
            if isinstance(clusters_payload, dict) and clusters_payload:
                failure_diagnostics_section = self._failure_diagnostics_section_html(
                    clusters_payload,
                    payload.get("metric_clusters_overview"),
                    platform_base_url=payload.get("platform_base_url"),
                    call_import_id=str(payload.get("call_import_id") or ""),
                    evaluation_id=str(payload.get("evaluation_id") or ""),
                )

        prompt_improvements_section = ""
        if is_internal and show_prompt_improvements:
            improvements_payload = payload.get("prompt_improvements")
            if isinstance(improvements_payload, dict) and improvements_payload:
                prompt_improvements_section = self._prompt_improvements_section_html(
                    improvements_payload
                )

        business_section = ""
        if insight_blocks and show_user_insights:
            intro = (
                "User-insight classifiers emit distributions across operational categories. "
                "These are separate from the quality metric panel and are scored during the same per-call evaluation pass."
                if is_internal
                else "User insights are identified by analyzing patterns across LLM rationales and diarized transcripts from the evaluation run."
            )
            business_section = f"""
            <section>
              <!-- 03 User Insights -->
              <h2>03 User Insights</h2>
              <p class="method">{intro}</p>
              {''.join(insight_blocks)}
            </section>
            """

        weekly_meta = payload.get("weekly_delta_meta") or {}
        weekly_methodology = ""
        if payload.get("include_weekly_delta"):
            missing = int(weekly_meta.get("missing_dates") or 0)
            current = int(weekly_meta.get("current_count") or 0)
            previous = int(weekly_meta.get("previous_count") or 0)
            weekly_methodology = (
                " Weekly deltas compare completed rows in the latest recording-date "
                f"week (n={current}) with the immediately previous week (n={previous})."
                + (
                    f" {missing} completed row(s) without recording dates were excluded from delta calculations."
                    if missing
                    else ""
                )
            )

        design_notes_section = ""
        if show_design_notes and design_notes:
            notes = "".join(
                f"<li>{html.escape(str(note))}</li>"
                for note in design_notes[:8]
                if str(note).strip()
            )
            if notes:
                design_notes_section = f"""
                <section>
                  <h2>05 User Experience Design Notes</h2>
                  <ol class="design-notes">{notes}</ol>
                </section>
                """
        default_audit_summary = _clamp_prose_to_sentences(
            f'Quality audit from {payload["evaluation"].completed_rows} completed '
            f'calls across {len(quality_metrics)} quality metrics.'
        )
        audit_summary_text = (
            payload.get("audit_summary")
            or narrative.get("audit_summary")
            or default_audit_summary
        )
        audit_summary_markup = self._audit_summary_html(str(audit_summary_text))
        top_metric_strip_markup = ""
        top_metric_delta_markup = ""
        if show_audit_summary and quality_metrics:
            top_metric_strip_markup = self._top_metric_percentages_html(
                quality_metrics,
                limit=5,
            )
            if is_internal and include_weekly_delta:
                top_metric_delta_markup = self._top_metric_delta_line_graphs_html(
                    quality_metrics,
                    limit=5,
                )
        repeat_header_markup = (
            f'<div class="repeat-page-header"><img src="{internal_logo_uri}" alt="Internal brand" class="repeat-page-logo" /></div>'
            if internal_logo_uri
            else ""
        )

        return f"""
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8" />
          <style>
            @page {{
              size: A4;
              margin: 18mm 14mm 17mm 14mm;
              @top-left {{ content: element(repeatHeader); }}
              @bottom-center {{ content: "Page " counter(page) " of " counter(pages); color: #667085; font-size: 9px; }}
            }}
            @page:first {{
              @top-left {{ content: none; }}
            }}
            body {{ font-family: Helvetica, Arial, sans-serif; color: #111827; font-size: 11px; line-height: 1.4; }}
            header {{ border-bottom: 0; padding-bottom: 8px; margin-bottom: 12px; }}
            .brand-header {{ margin-bottom: 10px; }}
            .brand-logo-row {{ display: flex; align-items: center; justify-content: space-between; gap: 32px; min-height: 58px; margin-bottom: 8px; }}
            .brand-logo-slot {{ flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 5px; }}
            .brand-logo-slot-internal {{ align-items: flex-start; }}
            .brand-logo-slot-external {{ align-items: flex-end; text-align: right; }}
            .brand-placeholder {{ display: block; min-height: 1px; }}
            .brand-logo {{ max-width: 230px; max-height: 58px; object-fit: contain; }}
            .repeat-page-header {{ position: running(repeatHeader); height: 10mm; }}
            .repeat-page-logo {{ max-width: 92px; max-height: 28px; object-fit: contain; }}
            .brand-text {{ margin-top: 2px; font-size: 15px; font-weight: 800; line-height: 1.1; color: #111827; letter-spacing: .16em; text-transform: uppercase; }}
            .title-rule {{ height: 2px; background: #b85f4b; margin: 10px 0 10px; }}
            .eyebrow {{ text-transform: uppercase; letter-spacing: .34em; font-size: 10px; color: #b85f4b; font-weight: 800; margin-bottom: 10px; }}
            .eyebrow .dotsep {{ color: #7a756d; padding: 0 16px; letter-spacing: 0; }}
            .eyebrow .muted {{ color: #7a756d; }}
            h1 {{ font-size: 28px; font-weight: 800; margin: 4px 0; letter-spacing: .1px; }}
            .subtitle {{ font-size: 13px; color: #666; margin-bottom: 10px; }}
            h2 {{ font-size: 16px; margin: 16px 0 8px; color: #0b1220; border-bottom: 2px solid #0b1220; padding-bottom: 2px; }}
            h3 {{ font-size: 13px; margin: 0; }}
            .meta {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }}
            .summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }}
            .metric-group-title {{ font-size: 13px; margin: 12px 0 8px; color: #374151; text-transform: uppercase; letter-spacing: .08em; }}
            .box {{ border: 1px solid #d9dee8; padding: 7px 8px; border-radius: 6px; background: #f7f9fc; }}
            .box strong {{ display: block; font-size: 13px; color: #111827; }}
            .box span {{ color: #667085; font-size: 9px; text-transform: uppercase; letter-spacing: .04em; }}
            .metric {{ break-inside: avoid; border: 1px solid #d9dee8; border-radius: 2px; padding: 10px; margin-bottom: 10px; background: #fff; }}
            .metric-compact-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 8px; }}
            .metric-compact {{ padding: 9px 10px 8px; margin-bottom: 0; min-height: 148px; }}
            .metric-compact-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 6px; }}
            .metric-compact-head .metric-title {{ font-size: 9px; letter-spacing: .08em; color: #667085; font-weight: 800; }}
            .metric-compact-status {{ width: 7px; height: 7px; border-radius: 50%; background: #16a34a; margin-top: 2px; flex-shrink: 0; }}
            .metric-compact-body {{ display: flex; gap: 8px; align-items: stretch; }}
            .metric-compact-hero {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 8px; }}
            .metric-compact-main {{ flex: 1; min-width: 0; }}
            .metric-compact .metric-percent {{ font-size: 24px; margin-bottom: 4px; }}
            .metric-compact-delta {{ margin-top: 2px; }}
            .metric-compact-delta-row {{ display: grid; grid-template-columns: 68px 1fr auto; gap: 6px; align-items: center; font-size: 9px; color: #475569; }}
            .metric-compact-delta-row span {{ text-transform: lowercase; color: #667085; }}
            .metric-compact-delta-row strong {{ font-size: 10px; text-align: right; }}
            .metric-compact-delta-row small {{ color: #667085; white-space: nowrap; }}
            .metric-compact-delta.delta-good strong {{ color: #047857; }}
            .metric-compact-delta.delta-bad strong {{ color: #b42318; }}
            .metric-compact-delta.delta-flat strong {{ color: #475569; }}
            .metric-compact-delta-detail {{ display: block; margin-top: 3px; color: #667085; font-size: 9px; line-height: 1.3; }}
            .metric-compact-sparkline {{ flex-shrink: 0; width: 118px; }}
            .metric-sparkline {{ display: block; width: 100%; max-width: 118px; }}
            .metric-sparkline-area {{ fill: rgba(22, 163, 74, 0.12); stroke: none; }}
            .metric-sparkline-line {{ fill: none; stroke: #16a34a; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }}
            .metric-sparkline-dot {{ fill: #16a34a; }}
            .metric-sparkline-label {{ fill: #94a3b8; font-size: 7px; font-family: Helvetica, Arial, sans-serif; }}
            .metric-compact-meaning {{ margin: 8px 0 0; font-size: 10px; line-height: 1.35; color: #374151; }}
            .metric-compact-meta {{ margin-top: 6px; color: #94a3b8; font-size: 8px; letter-spacing: .02em; }}
            .metric-head {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #eef1f5; padding-bottom: 6px; margin-bottom: 7px; }}
            .metric-title {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; font-weight: 800; color: #1f2937; }}
            .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #b85f4b; margin-right: 8px; }}
            .metric-type {{ color: #7a756d; font-size: 10px; text-transform: uppercase; margin-top: 3px; }}
            .direction-badge {{ border: 1px solid #d7cfc2; background: #fff8f5; padding: 5px 8px; color: #7a756d; align-self: start; text-align: right; min-width: 104px; }}
            .direction-badge span {{ display: block; font-size: 9px; text-transform: uppercase; font-weight: 800; letter-spacing: .04em; }}
            .direction-badge strong {{ display: block; margin-top: 2px; color: #b85f4b; font-size: 11px; text-transform: uppercase; }}
            .metric-hero {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; }}
            .metric-percent {{ font-size: 27px; line-height: 1; font-weight: 800; color: #111; }}
            .metric-count {{ color: #7a756d; font-size: 10px; letter-spacing: .04em; font-weight: 800; }}
            .metric-count strong {{ color: #111827; font-size: 13px; letter-spacing: 0; margin-left: 8px; }}
            .metric-bar {{ height: 8px; background: #e7ddd1; border: 1px solid #d7cfc2; margin: 8px 0; }}
            .metric-bar-fill {{ height: 100%; background: #c7725e; }}
            .metric-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
            .metric-grid div {{ background: #f8fafc; border-radius: 6px; padding: 7px 8px; min-height: 40px; }}
            .metric-grid strong, .measurement-grid strong {{ display: block; color: #111827; font-size: 13px; line-height: 1.25; overflow-wrap: anywhere; word-break: normal; }}
            .metric-grid small, .measurement-grid small {{ display: block; margin-top: 4px; color: #667085; font-size: 9px; line-height: 1.2; text-transform: uppercase; letter-spacing: .04em; }}
            .delta-card {{ margin-top: 8px; border: 1px solid #d9dee8; border-radius: 6px; padding: 8px 9px; background: #f8fafc; }}
            .delta-head {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 5px; }}
            .delta-head span {{ color: #667085; font-size: 9px; text-transform: uppercase; letter-spacing: .05em; font-weight: 800; }}
            .delta-head strong {{ font-size: 12px; }}
            .delta-good .delta-head strong {{ color: #047857; }}
            .delta-bad .delta-head strong {{ color: #b42318; }}
            .delta-flat .delta-head strong {{ color: #475569; }}
            .delta-bars {{ display: grid; gap: 4px; }}
            .delta-row {{ display: grid; grid-template-columns: 58px 1fr 42px; gap: 7px; align-items: center; }}
            .delta-row span {{ color: #475569; font-size: 9px; font-weight: 700; }}
            .delta-row b {{ text-align: right; font-size: 9px; }}
            .delta-track {{ height: 7px; background: #e7ddd1; border: 1px solid #d7cfc2; }}
            .delta-fill {{ height: 100%; }}
            .delta-fill-prev {{ background: #94a3b8; }}
            .delta-fill-current {{ background: #c7725e; }}
            .delta-benchmark {{ margin-top: 4px; color: #475569; font-size: 9px; line-height: 1.3; }}
            .measurement-grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 8px; margin-top: 8px; }}
            .measurement-grid div {{ background: #fff8f5; border: 1px solid #f3d3c5; border-radius: 6px; padding: 7px 8px; min-height: 40px; }}
            .distribution {{ margin: 8px 0 0; color: #374151; }}
            .meaning {{ margin: 8px 0 0; color: #444; font-size: 13px; line-height: 1.45; }}
            .distribution-bars {{ margin-top: 10px; }}
            .subhead {{ font-size: 10px; text-transform: uppercase; letter-spacing: .05em; color: #7a756d; font-weight: 800; margin-bottom: 5px; }}
            .dist-row {{ display: grid; grid-template-columns: 110px 1fr 74px; gap: 8px; align-items: center; margin: 4px 0; }}
            .dist-label {{ font-size: 10px; font-weight: 700; color: #1f2937; overflow-wrap: anywhere; }}
            .dist-track {{ height: 9px; background: #e7ddd1; border: 1px solid #d7cfc2; }}
            .dist-fill {{ height: 100%; background: #c7725e; }}
            .dist-value {{ text-align: right; font-size: 10px; font-weight: 800; color: #111827; }}
            .empty-bars {{ color: #667085; font-size: 10px; font-style: italic; }}
            .insight-block {{ break-inside: avoid; margin: 14px 0 18px; }}
            .insight-heading {{ margin-bottom: 8px; }}
            .insight-heading h3 {{ margin: 0; }}
            .insight-body {{ display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 14px; align-items: start; }}
            .insight-table-col {{ min-width: 0; }}
            .insight-sidecol {{ display: grid; gap: 10px; min-width: 0; }}
            .insight-overview-box {{ break-inside: avoid; margin: 0 0 16px; padding: 12px 14px; border: 1px solid #e7ddd1; border-radius: 8px; background: #faf7f2; }}
            .insight-overview-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: #7a756d; font-weight: 800; margin-bottom: 6px; }}
            .insight-overview-box p {{ margin: 0; color: #374151; line-height: 1.5; }}
            .insight-callout {{ border: 1px solid #eadfce; border-radius: 8px; padding: 10px 12px; }}
            .insight-observation-box {{ background: #fdf3f0; border-color: #f0d4cb; }}
            .insight-evidence-box {{ background: #faf6ef; border-color: #eadfce; }}
            .insight-callout-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: #b85f4b; font-weight: 800; margin-bottom: 6px; }}
            .insight-callout p {{ margin: 0 0 6px; color: #374151; line-height: 1.45; }}
            .insight-callout p:last-child {{ margin-bottom: 0; }}
            .insight-evidence-id {{ color: #7a756d; font-size: 9px; margin-top: 4px; }}
            .insight-table td:nth-child(2), .insight-table td:nth-child(4) {{ white-space: nowrap; font-weight: 800; }}
            .insight-track {{ height: 9px; background: #e8edff; border: 1px solid #cfd8ff; min-width: 120px; }}
            .insight-fill {{ height: 100%; background: #4f46e5; }}
            .failure-diagnostics {{ margin-top: 4px; max-width: 100%; }}
            .failure-diagnostics-intro {{ break-inside: auto; margin-bottom: 6px; max-width: 100%; }}
            .failure-diagnostics-intro h2 {{ margin-bottom: 4px; }}
            .failure-diagnostics .method {{ margin: 0 0 6px; }}
            .failure-diagnostics .insight-block {{ margin: 6px 0 8px; break-inside: auto; }}
            .failure-diagnostics-metrics {{ display: grid; gap: 8px; max-width: 100%; }}
            .fd-summary-box {{
              break-inside: auto;
              margin: 0 0 8px;
              padding: 8px 10px;
              max-width: 100%;
              overflow: hidden;
              box-sizing: border-box;
            }}
            .fd-summary-box .insight-table {{
              margin-top: 4px;
              width: 100%;
              max-width: 100%;
              table-layout: fixed;
            }}
            .fd-summary-table th, .fd-level1-table th {{ font-size: 9px; }}
            .fd-summary-table td, .fd-level1-table td {{
              font-size: 10px;
              padding: 5px 6px;
              overflow-wrap: anywhere;
              white-space: normal;
            }}
            .fd-summary-table .fd-col-metric {{ width: 24%; }}
            .fd-summary-table .fd-col-num {{ width: 11%; }}
            .fd-summary-table .fd-col-preview {{ width: 54%; }}
            .failure-diagnostics .fd-summary-table td.fd-col-num {{
              white-space: nowrap;
              font-weight: 800;
              text-align: right;
            }}
            .failure-diagnostics .fd-summary-table td.fd-col-preview {{
              white-space: normal;
              font-weight: 400;
            }}
            .failure-diagnostics .fd-level1-table td:nth-child(2),
            .failure-diagnostics .fd-level1-table td:nth-child(3) {{
              white-space: normal;
              font-weight: 400;
            }}
            .fd-preview-list {{
              margin: 0;
              padding-left: 14px;
              list-style: disc;
              color: #374151;
              line-height: 1.35;
            }}
            .fd-preview-list li {{ margin: 0 0 3px; }}
            .fd-preview-list li:last-child {{ margin-bottom: 0; }}
            .fd-preview-more {{ color: #6b7280; font-style: italic; list-style: none; margin-left: -14px; }}
            .fd-level1-table {{
              width: 100%;
              max-width: 100%;
              table-layout: fixed;
              margin: 0 0 8px;
            }}
            .fd-level1-table .fd-col-index {{ width: 6%; }}
            .fd-level1-table .fd-col-cluster {{ width: 34%; }}
            .fd-level1-table .fd-col-gap {{ width: 14%; }}
            .fd-level1-table .fd-col-num {{ width: 9%; }}
            .fd-level1-table .fd-col-share {{ width: 9%; }}
            .fd-level1-table .fd-col-bar {{ width: 28%; }}
            .failure-diagnostics .fd-level1-table td.fd-col-num,
            .failure-diagnostics .fd-level1-table td:nth-child(5) {{
              white-space: nowrap;
              font-weight: 800;
            }}
            .failure-diagnostics .insight-track {{
              min-width: 0;
              max-width: 100%;
              width: 100%;
            }}
            .fd-summary-discovered-row td {{ background: #f8fafc; }}
            .fd-num {{ color: #6b7280; font-weight: 800; width: 24px; }}
            .fd-breakdown-caption {{ margin: 0 0 4px; font-size: 9px; color: #6b7280; text-transform: uppercase; letter-spacing: .04em; font-weight: 700; }}
            .fd-discovered-block {{ margin-top: 4px; padding-top: 6px; border-top: 1px solid #e5e7eb; max-width: 100%; }}
            .fd-rca-block {{ margin: 10px 0 12px; max-width: 100%; overflow: hidden; box-sizing: border-box; }}
            .fd-rca-block h3 {{ margin: 0 0 4px; font-size: 12px; }}
            .fd-rca-base {{ margin: 0 0 6px; font-size: 9px; }}
            .fd-rca-patterns-wrap {{ width: 100%; max-width: 100%; margin: 0 auto; overflow: hidden; box-sizing: border-box; }}
            .fd-rca-table {{ table-layout: fixed; width: 100%; max-width: 100%; box-sizing: border-box; }}
            .fd-rca-table td, .fd-rca-table th {{ font-size: 10px; padding: 5px 4px; overflow-wrap: anywhere; word-break: break-word; box-sizing: border-box; }}
            .fd-rca-patterns-table {{ margin-left: auto; margin-right: auto; }}
            .fd-rca-patterns-table .fd-rca-col-finding {{ width: 41%; text-align: left; }}
            .fd-rca-patterns-table th.fd-rca-col-finding {{ text-align: left; }}
            .fd-rca-patterns-table .fd-rca-col-pct {{ width: 12%; white-space: nowrap; text-align: center; font-weight: 800; vertical-align: top; }}
            .fd-rca-patterns-table th.fd-rca-col-pct {{ text-align: center; }}
            .fd-rca-patterns-table .fd-rca-col-bar {{ width: 29%; vertical-align: middle; padding-left: 6px; padding-right: 6px; }}
            .fd-rca-patterns-table th.fd-rca-col-bar {{ text-align: center; }}
            .fd-rca-patterns-table .fd-rca-col-count {{ width: 18%; white-space: nowrap; text-align: center; font-weight: 800; vertical-align: top; }}
            .fd-rca-patterns-table th.fd-rca-col-count {{ text-align: center; }}
            .fd-rca-track {{ height: 9px; background: #e7ddd1; border: 1px solid #d7cfc2; min-width: 0; max-width: 100%; width: 100%; box-sizing: border-box; }}
            .fd-rca-fill {{ height: 100%; background: #c7725e; max-width: 100%; }}
            .fd-rca-hotspots-table .fd-rca-col-pct {{ white-space: nowrap; text-align: center; font-weight: 800; width: 14%; }}
            .fd-rca-hotspots-table .fd-rca-col-bar {{ width: 28%; }}
            .fd-rca-hotspots-table .fd-rca-col-count {{ white-space: nowrap; text-align: center; font-weight: 800; width: 14%; vertical-align: top; }}
            .fd-finding-sub {{ margin-top: 3px; font-size: 9px; color: #6b7280; font-weight: 400; line-height: 1.35; }}
            .fd-evidence-line {{ font-size: 8px; color: #6b7280; font-weight: 600; line-height: 1.3; }}
            .fd-evidence-primary {{ font-size: 10px; font-weight: 800; color: #111827; line-height: 1.3; }}
            .fd-cluster-appendix {{ margin-top: 14px; padding-top: 10px; border-top: 1px solid #e5e7eb; break-inside: avoid; }}
            .fd-cluster-appendix h3 {{ margin: 0 0 4px; font-size: 11px; }}
            .fd-rca-interpretation {{ margin-top: 6px; }}
            .fd-rca-summary-grid {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 10px; align-items: start; }}
            .fd-rca-twocol {{ display: grid; gap: 8px; }}
            .fd-rca-mini-table {{ table-layout: fixed; width: 100%; }}
            .fd-why-flagged {{ margin: 0 0 6px; font-size: 10px; color: #374151; line-height: 1.4; }}
            .insight-evidence-id a {{ color: #b85f4b; font-weight: 700; text-decoration: none; }}
            .metric-cluster-metric-group {{
              margin: 0;
              padding: 8px 0;
              border-top: 1px solid #e5e7eb;
              break-inside: auto;
            }}
            .metric-cluster-metric-group:first-child {{ border-top: none; padding-top: 4px; }}
            .metric-cluster-metric-head {{
              display: flex;
              justify-content: space-between;
              align-items: baseline;
              gap: 8px;
              margin-bottom: 4px;
            }}
            .metric-cluster-metric-head h3 {{ margin: 0; font-size: 13px; }}
            .metric-cluster-metric-head span {{
              color: #6b7280;
              font-size: 9px;
              font-weight: 700;
              text-transform: uppercase;
              letter-spacing: .03em;
              white-space: normal;
              text-align: right;
              flex-shrink: 1;
              min-width: 0;
            }}
            .metric-cluster-detail-section-title {{ margin-top: 6px; }}
            .metric-cluster-details {{ display: grid; gap: 6px; }}
            .metric-cluster-detail {{
              border: 1px solid #e5e7eb;
              border-radius: 6px;
              background: #fff;
              padding: 6px 8px;
              break-inside: auto;
              page-break-inside: auto;
            }}
            .metric-cluster-detail-compact .insight-callout {{ margin-top: 4px; }}
            .fd-cluster-observation {{ margin: 0 0 4px; font-size: 10px; color: #374151; line-height: 1.35; }}
            .fd-omitted-metrics {{ margin: 6px 0 8px; font-size: 9px; }}
            .metric-cluster-detail-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 4px; }}
            .metric-cluster-detail-head h4 {{ margin: 0; font-size: 11px; font-weight: 800; color: #111827; line-height: 1.3; }}
            .metric-cluster-detail-head span {{
              color: #6b7280;
              font-size: 9px;
              font-weight: 700;
              text-transform: uppercase;
              letter-spacing: .03em;
              white-space: normal;
              text-align: right;
              flex-shrink: 1;
              min-width: 0;
            }}
            .metric-cluster-detail-body {{ grid-template-columns: 1.1fr 0.9fr; gap: 10px; }}
            .metric-cluster-detail-body .subhead {{ margin-bottom: 3px; }}
            .metric-cluster-sub-bars {{ margin: 0; }}
            .metric-cluster-sub-row {{ margin: 2px 0; grid-template-columns: 96px 1fr 62px; gap: 6px; }}
            .metric-cluster-sub-fill {{ background: #6366f1; }}
            .insight-callout-empty p {{ margin: 0; }}
            .insight-observation, .insight-evidence {{ margin: 0; color: #374151; }}
            .insight-evidence span {{ color: #7a756d; font-size: 9px; margin-left: 6px; }}
            .design-notes {{ margin: 8px 0 0; padding-left: 18px; }}
            .design-notes li {{ margin-bottom: 8px; line-height: 1.5; }}
            .gap-badge {{ display: inline-block; font-size: 9px; font-weight: 800; letter-spacing: .04em; color: #b42318; text-transform: uppercase; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
            th, td {{ text-align: left; border-bottom: 1px solid #e5e7eb; padding: 7px; vertical-align: top; }}
            th {{ background: #111827; color: #fff; font-size: 10px; text-transform: uppercase; }}
            .method {{ color: #475467; line-height: 1.5; }}
            .audit-summary p {{ margin: 0 0 7px; }}
            .audit-summary ul {{ margin: 7px 0 10px; padding-left: 16px; }}
            .audit-summary li {{ margin-bottom: 5px; }}
            .audit-summary-section {{ margin-bottom: 0; break-after: avoid; page-break-after: avoid; }}
            .audit-summary-section + section {{ margin-top: 0; }}
            .audit-summary-section + section h2 {{ margin-top: 12px; }}
            .audit-stat-strip {{ display: flex; gap: 0; margin: 14px 0 0; border-top: 1px solid #111827; break-after: avoid; page-break-after: avoid; }}
            .audit-stat-strip:last-child {{ margin-bottom: 18px; }}
            .audit-stat-card {{ flex: 1; min-width: 0; padding: 10px 12px 12px 0; }}
            .audit-stat-card + .audit-stat-card {{ border-left: 1px solid #d1d5db; padding-left: 12px; }}
            .audit-stat-rule {{ display: none; }}
            .audit-stat-label {{ font-size: 8px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; color: #d16532; margin-bottom: 6px; line-height: 1.3; }}
            .audit-stat-value {{ font-family: Georgia, 'Times New Roman', serif; font-size: 28px; font-weight: 700; color: #111827; line-height: 1; }}
            .audit-delta-panel {{ break-inside: auto; page-break-inside: auto; margin: 8px 0 12px; padding-top: 8px; border-top: 1px solid #e5e7eb; }}
            .audit-delta-title {{ font-size: 13px; font-weight: 900; letter-spacing: .04em; text-transform: uppercase; color: #111827; margin-bottom: 8px; }}
            .audit-delta-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
            .audit-delta-card {{ break-inside: auto; page-break-inside: auto; border: 1px solid #d9dee8; border-radius: 6px; padding: 8px 9px; background: #f8fafc; min-height: 96px; }}
            .audit-delta-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 4px; }}
            .audit-delta-head-main {{ min-width: 0; }}
            .audit-delta-head span {{ display: block; color: #111827; font-size: 9px; font-weight: 900; letter-spacing: .06em; line-height: 1.25; text-transform: uppercase; overflow-wrap: anywhere; }}
            .audit-delta-direction {{ display: block; margin-top: 2px; color: #94a3b8; font-size: 7px; font-weight: 600; letter-spacing: .03em; text-transform: none; }}
            .audit-delta-head strong {{ flex-shrink: 0; font-size: 10px; line-height: 1.2; text-align: right; white-space: nowrap; }}
            .audit-delta-card.delta-good .audit-delta-head strong {{ color: #047857; }}
            .audit-delta-card.delta-bad .audit-delta-head strong {{ color: #b42318; }}
            .audit-delta-card.delta-flat .audit-delta-head strong {{ color: #475569; }}
            .audit-delta-chart {{ min-height: 50px; }}
            .audit-delta-chart .metric-sparkline {{ width: 100%; max-width: 100%; }}
            .audit-delta-empty {{ height: 50px; display: flex; align-items: center; justify-content: center; border: 1px dashed #cbd5e1; background: #fff; color: #667085; font-size: 9px; }}
            .audit-delta-reason {{ margin: 6px 0 0; padding-top: 5px; border-top: 1px solid #e5e7eb; color: #374151; font-size: 10px; font-weight: 600; line-height: 1.45; }}
            .report-footer {{ margin-top: 24px; border-top: 1px solid #1f2937; padding-top: 10px; display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; color: #4b5563; font-size: 10px; }}
            .footer-left, .footer-right {{ display: flex; flex-direction: column; gap: 3px; }}
            .footer-right {{ text-align: right; }}
            .brand-title {{ color: #111827; font-weight: 800; font-size: 11px; letter-spacing: .2px; }}
            .brand-link {{ color: #d16532; font-weight: 700; text-decoration: none; }}
            .prompt-improvements {{ margin-top: 4px; max-width: 100%; }}
            .prompt-improvement-card {{
              margin: 0 0 10px;
              padding: 8px 10px;
              border: 1px solid #e5e7eb;
              border-radius: 6px;
              background: #fafafa;
              max-width: 100%;
              box-sizing: border-box;
              break-inside: auto;
              page-break-inside: auto;
            }}
            .prompt-improvements .metric-cluster-metric-head h3 {{
              flex: 1;
              min-width: 0;
              overflow-wrap: anywhere;
              word-break: break-word;
            }}
            .prompt-improvements .method {{
              overflow-wrap: anywhere;
              word-break: break-word;
              max-width: 100%;
            }}
            .prompt-suggestion-block {{
              margin: 6px 0;
              padding: 8px 10px;
              border: 1px solid #e5e7eb;
              border-radius: 6px;
              background: #fff;
              font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
              font-size: 9px;
              line-height: 1.45;
              color: #111827;
              white-space: pre-wrap;
              overflow-wrap: anywhere;
              word-break: break-word;
              max-width: 100%;
              width: 100%;
              box-sizing: border-box;
            }}
            .prompt-improvement-meta {{
              display: inline-flex;
              flex-wrap: wrap;
              align-items: center;
              gap: 6px;
            }}
            .prompt-change-badge {{
              display: inline-block;
              font-size: 8px;
              font-weight: 800;
              text-transform: uppercase;
              letter-spacing: .06em;
              border-radius: 4px;
              padding: 2px 5px;
              border: 1px solid transparent;
            }}
            .prompt-change-badge-edit {{
              color: #9f1239;
              background: #fff1f2;
              border-color: #fecdd3;
            }}
            .prompt-change-badge-add {{
              color: #065f46;
              background: #ecfdf5;
              border-color: #a7f3d0;
            }}
            .prompt-change-grid {{
              display: grid;
              grid-template-columns: repeat(2, minmax(0, 1fr));
              gap: 8px;
              margin: 8px 0;
            }}
            .prompt-change-box {{
              border-radius: 6px;
              padding: 8px 10px;
              min-width: 0;
            }}
            .prompt-change-before {{
              border: 1px solid #fecdd3;
              background: #fff1f2;
            }}
            .prompt-change-after {{
              border: 1px solid #a7f3d0;
              background: #ecfdf5;
            }}
            .prompt-change-add {{
              border: 1px solid #e5e7eb;
              background: #fff;
              margin: 8px 0;
            }}
            .prompt-change-label {{
              font-size: 8px;
              font-weight: 800;
              text-transform: uppercase;
              letter-spacing: .08em;
              margin-bottom: 6px;
            }}
            .prompt-change-before .prompt-change-label {{ color: #be123c; }}
            .prompt-change-after .prompt-change-label {{ color: #047857; }}
            .prompt-change-add .prompt-change-label {{ color: #6b7280; }}
            .prompt-change-text {{
              font-size: 9px;
              line-height: 1.45;
              color: #111827;
              white-space: pre-wrap;
              overflow-wrap: anywhere;
              word-break: break-word;
            }}
            .prompt-improvement-rationale {{
              margin-top: 6px;
            }}
          </style>
        </head>
        <body>
          {repeat_header_markup}
          <header>
            {brand_header_markup}
            <div class="eyebrow">Quality Metric Audit <span class="dotsep">·</span> <span class="muted">Weekly</span></div>
            <div class="title-rule"></div>
            <h1>{html.escape(payload["title"])}</h1>
            <div class="subtitle">{html.escape(payload["subtitle"])}</div>
            <div class="meta">
              <div class="box"><span>Client</span><strong>{html.escape(payload["vendor_name"])}</strong></div>
              <div class="box"><span>Use Case</span><strong>{html.escape(payload.get("use_case") or "Not specified")}</strong></div>
              <div class="box"><span>Window</span><strong>{html.escape(payload.get("period_display") or "Not specified")}</strong></div>
              <div class="box"><span>Calls</span><strong>{payload["evaluation"].total_rows}</strong></div>
              <div class="box"><span>Audit Set</span><strong>{len(metrics)} metrics</strong></div>
            </div>
          </header>
          {f'''
          <section class="audit-summary-section">
            <h2>01 Audit Summary</h2>
            <div class="audit-summary method">{audit_summary_markup}</div>
            {top_metric_strip_markup}
            {top_metric_delta_markup}
          </section>
          ''' if show_audit_summary else ''}
          {quality_panel_markup}
          {business_section}
          {failure_diagnostics_section}
          {prompt_improvements_section}
          {design_notes_section}
          {f'''
          <section>
            <h2>Methodology</h2>
            <p class="method">This report is generated from completed Call Import evaluation results. Metrics are derived from the saved evaluation outputs and the transcript source configured for the run.{html.escape(weekly_methodology)}</p>
          </section>
          ''' if show_methodology else ''}
          <div class="report-footer">
            <div class="footer-left">
              <div class="brand-title">Powered by EfficientAI</div>
              <div>Voice AI Evaluation Platform</div>
              <div>Website: <a href="https://efficientai.cloud" class="brand-link">https://efficientai.cloud</a></div>
            </div>
            <div class="footer-right">
              <div>Evaluation ID: {html.escape(str(getattr(payload["evaluation"], "id", "")))}</div>
              <div>Generated: {html.escape(payload["generated_at_iso"])}</div>
              <div>Call import reports by EfficientAI Cloud</div>
            </div>
          </div>
        </body>
        </html>
        """

    def _render_weasyprint(
        self,
        html_content: str,
        *,
        label: str = "",
    ) -> bytes | None:
        try:
            from weasyprint import HTML  # type: ignore
        except Exception:
            return None
        try:
            import time

            started = time.perf_counter()
            pdf_bytes = HTML(string=html_content).write_pdf()
            elapsed = time.perf_counter() - started
            logger.info(
                "WeasyPrint PDF rendered in {:.1f}s (html_chars={}, {})",
                elapsed,
                len(html_content),
                label or "report",
            )
            return pdf_bytes
        except Exception as exc:  # pragma: no cover - depends on native libs
            logger.warning("Falling back to basic PDF renderer: {}", exc)
            return None

    def _plain_text_lines(self, payload: dict[str, Any]) -> list[str]:
        metrics: list[MetricReportSummary] = payload["metrics"]
        metric_insights = (
            payload.get("metric_insights")
            if isinstance(payload.get("metric_insights"), dict)
            else {}
        )
        lines = [
            payload["custom_heading"] or "",
            "QUALITY METRIC AUDIT",
            payload["title"],
            payload["subtitle"],
            f"Client: {payload['vendor_name']}",
            f"Generated: {payload['generated_at']}",
            f"Window: {payload.get('period_display') or 'Not specified'}",
            f"Calls: {payload['evaluation'].total_rows}",
            f"Audit Set: {len(metrics)} metrics",
            "",
            "02 Quality Metric Panel",
        ]
        for summary in metrics:
            clear_count = max(summary.evaluated_count - summary.flagged_count, 0)
            business_meaning = (
                str(metric_insights.get(summary.id) or "").strip()
                or self._short_business_meaning(summary)
            )
            if payload.get("internal"):
                metric_lines = [
                    f"Metric: {summary.name}",
                    f"Type: {summary.metric_type}",
                    f"Measurement standpoint: {self._measurement_label(summary)}",
                    f"Current result: {self._metric_result(summary)}",
                    f"Flagged / positive calls: {summary.flagged_count}",
                    f"Evaluated calls: {summary.evaluated_count}",
                    f"Flagged rate: {self._percent(summary.flagged_count, summary.evaluated_count)}",
                    f"Clear / passing rate: {self._percent(clear_count, summary.evaluated_count)}",
                    f"Business meaning: {business_meaning}",
                ]
            else:
                metric_lines = [
                    f"Metric: {summary.name}",
                    f"Current week: {self._primary_metric_label(summary)}",
                    business_meaning,
                    f"{summary.flagged_count} of {summary.evaluated_count} · acc "
                    f"{self._percent(summary.evaluated_count, payload['evaluation'].total_rows)}",
                ]
            if payload.get("include_weekly_delta"):
                metric_lines.append(
                    "Weekly delta: "
                    f"{summary.weekly_delta_label or 'No previous-week baseline'}"
                    + (
                        f" ({summary.weekly_delta_detail})"
                        if summary.weekly_delta_detail
                        else ""
                    )
                )
            metric_lines.append("")
            lines.extend(metric_lines)
        business_metrics = [m for m in metrics if m.is_business_metric]
        generated_insights = payload.get("generated_user_insights")
        generated_list = (
            [item for item in generated_insights if isinstance(item, dict)]
            if isinstance(generated_insights, list)
            else []
        )
        is_internal = bool(payload.get("internal"))
        if business_metrics and is_internal:
            lines.extend(["03 User Insights"])
            for summary in business_metrics:
                lines.append(
                    f"{summary.name} | n={summary.evaluated_count} | "
                    f"{self._top_distribution_with_percentages(summary)}"
                )
                for call_id, rationale in summary.rationales[:4]:
                    lines.append(f"{summary.name} | {call_id} | {rationale}")
        elif business_metrics:
            lines.extend(["03 Business Insights"])
            for summary in business_metrics:
                lines.append(
                    f"{summary.name} | n={summary.evaluated_count} | "
                    f"{self._top_distribution_with_percentages(summary)}"
                )
        if generated_list and not is_internal:
            lines.extend(["03 User Insights"])
            overview = payload.get("user_insights_overview")
            if overview:
                lines.append(str(overview))
            for insight in generated_list:
                title = str(insight.get("title") or "User insight")
                lines.append(title)
                observation = insight.get("observation")
                if observation:
                    lines.append(f"Observation: {observation}")
                evidence = insight.get("evidence")
                if isinstance(evidence, dict):
                    quote = evidence.get("quote")
                    if quote:
                        lines.append(f"Quote: {quote}")
        if not (business_metrics and is_internal) and not (generated_list and not is_internal):
            lines.extend(
                ["04 User Insights / RCA" if business_metrics else "03 User Insights / RCA"]
            )
            has_rationale = False
            for summary in metrics:
                for call_id, rationale in summary.rationales[:4]:
                    has_rationale = True
                    lines.append(f"{summary.name} | {call_id} | {rationale}")
            if not has_rationale:
                lines.append("No flagged-call rationales were captured for this run.")
        lines = [line for line in lines if line]
        lines.extend(
            [
                "",
                "Methodology",
                "This report is generated from completed Call Import evaluation results. "
                "Metrics are derived from saved evaluation outputs and the transcript source configured for the run.",
            ]
        )
        if payload.get("include_weekly_delta"):
            meta = payload.get("weekly_delta_meta") or {}
            lines.append(
                "Weekly deltas compare completed rows in the latest recording-date "
                f"week (n={int(meta.get('current_count') or 0)}) with the "
                f"immediately previous week (n={int(meta.get('previous_count') or 0)})."
            )
            missing = int(meta.get("missing_dates") or 0)
            if missing:
                lines.append(
                    f"{missing} completed row(s) without recording dates were excluded from delta calculations."
                )
        lines.extend(
            [
                "",
                "Website: https://efficientai.cloud",
                "Call import reports by EfficientAI Cloud",
            ]
        )
        return lines

    def _render_basic_pdf(self, lines: Iterable[str]) -> bytes:
        wrapped: list[str] = []
        for line in lines:
            if not line:
                wrapped.append("")
                continue
            wrapped.extend(textwrap.wrap(line, width=92) or [""])

        page_lines: list[list[str]] = []
        page_size = 44
        for idx in range(0, len(wrapped), page_size):
            page_lines.append(wrapped[idx : idx + page_size])
        if not page_lines:
            page_lines = [["Quality Metric Audit"]]

        objects: list[bytes] = []
        page_ids: list[int] = []
        content_ids: list[int] = []
        next_id = 4
        for _ in page_lines:
            page_ids.append(next_id)
            content_ids.append(next_id + 1)
            next_id += 2

        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        kids = " ".join(f"{pid} 0 R" for pid in page_ids).encode("ascii")
        objects.append(
            b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(page_ids)).encode("ascii") + b" >>"
        )
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

        for page_id, content_id, page in zip(page_ids, content_ids, page_lines):
            stream = self._pdf_text_stream(page)
            objects.append(
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode(
                    "ascii"
                )
            )
            objects.append(
                b"<< /Length "
                + str(len(stream)).encode("ascii")
                + b" >>\nstream\n"
                + stream
                + b"\nendstream"
            )

        buffer = io.BytesIO()
        buffer.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for index, obj in enumerate(objects, start=1):
            offsets.append(buffer.tell())
            buffer.write(f"{index} 0 obj\n".encode("ascii"))
            buffer.write(obj)
            buffer.write(b"\nendobj\n")
        xref_offset = buffer.tell()
        buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        buffer.write(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            buffer.write(f"{offset:010d} 00000 n \n".encode("ascii"))
        buffer.write(
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
                "ascii"
            )
        )
        return buffer.getvalue()

    def _pdf_text_stream(self, lines: list[str]) -> bytes:
        commands = ["BT", "/F1 10 Tf", "50 790 Td", "14 TL"]
        for line in lines:
            commands.append(f"({self._pdf_escape(line)}) Tj")
            commands.append("T*")
        commands.append("ET")
        return "\n".join(commands).encode("latin-1", errors="replace")

    def _pdf_escape(self, text: str) -> str:
        return (
            text.encode("latin-1", errors="replace")
            .decode("latin-1")
            .replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )


call_import_evaluation_pdf_report_service = CallImportEvaluationPdfReportService()
