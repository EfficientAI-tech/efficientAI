"""PDF report rendering for Call Import evaluation results."""

from __future__ import annotations

import html
import io
import math
import textwrap
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
    group_name: str = "Quality Metrics"


class CallImportEvaluationPdfReportService:
    """Render external/internal Quality Metric Audit PDFs.

    WeasyPrint is used when the optional reporting dependency is installed.
    A small built-in PDF renderer keeps the endpoint usable in lean test/dev
    environments where optional native PDF dependencies are absent.
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
    ) -> bytes:
        generated_at = generated_at or datetime.now(timezone.utc)
        summaries = self._summarize_metrics(metrics, rows)
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
        }
        html_content = self._render_html(payload)
        pdf_bytes = self._render_weasyprint(html_content)
        if pdf_bytes:
            return pdf_bytes
        return self._render_basic_pdf(self._plain_text_lines(payload))

    def _summarize_metrics(
        self,
        metrics: list[Metric],
        rows: list[tuple[CallImportEvaluationRow, CallImportRow]],
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
                if self._is_flagged(value):
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

    def _render_html(self, payload: dict[str, Any]) -> str:
        metrics: list[MetricReportSummary] = payload["metrics"]
        report_config = payload.get("report_config") if isinstance(payload.get("report_config"), dict) else {}
        sections = report_config.get("sections") if isinstance(report_config.get("sections"), dict) else {}
        show_audit_summary = sections.get("audit_summary", True)
        show_quality_panel = sections.get("quality_panel", True)
        show_user_insights = sections.get("user_insights", True)
        show_design_notes = sections.get("design_notes", True)
        show_methodology = sections.get("methodology", True)
        narrative = payload.get("narrative") if isinstance(payload.get("narrative"), dict) else {}
        observations = narrative.get("observations") if isinstance(narrative.get("observations"), dict) else {}
        evidence = narrative.get("evidence") if isinstance(narrative.get("evidence"), dict) else {}
        design_notes = narrative.get("design_notes") if isinstance(narrative.get("design_notes"), list) else []
        insight_config = {}
        for item in report_config.get("insights", []) if isinstance(report_config.get("insights"), list) else []:
            if isinstance(item, dict) and item.get("metric_id"):
                insight_config[str(item["metric_id"])] = item
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
                else '<span class="brand-placeholder">Internal brand</span>'
            )
            external_img = (
                f'<img src="{external_logo_uri}" alt="External vendor brand" class="brand-logo" />'
                if external_logo_uri
                else '<span class="brand-placeholder">Vendor brand</span>'
            )
            logo_markup = (
                '<div class="brand-logo-slot brand-logo-slot-internal">'
                '<div class="brand-role">Internal brand</div>'
                f"{internal_img}</div>"
                '<div class="brand-logo-slot brand-logo-slot-external">'
                '<div class="brand-role">Vendor brand</div>'
                f"{external_img}</div>"
            )
        heading_markup = (
            f'<div class="brand-text">{html.escape(payload["custom_heading"])}</div>'
            if payload.get("custom_heading")
            else ""
        )
        brand_header_markup = (
            f'<div class="brand-header"><div class="brand-logo-row">{logo_markup}</div>{heading_markup}</div>'
            if logo_markup or heading_markup
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
        for summary in quality_metrics:
            clear_count = max(summary.evaluated_count - summary.flagged_count, 0)
            primary_pct = self._primary_metric_percent(summary)
            delta_markup = (
                f"""
                  <div class="weekly-delta">
                    <strong>{html.escape(summary.weekly_delta_label or "No previous-week baseline")}</strong>
                    <small>{html.escape(summary.weekly_delta_detail or "")}</small>
                  </div>
                """
                if payload.get("include_weekly_delta")
                else ""
            )
            card = (
                f"""
                <article class="metric">
                  <div class="metric-head">
                    <div>
                      <div class="metric-title"><span class="dot"></span>{html.escape(summary.name)}</div>
                      <div class="metric-type">{html.escape(summary.metric_type)}</div>
                    </div>
                    <span class="direction">LOWER IS BETTER</span>
                  </div>
                  <div class="metric-hero">
                    <div class="metric-percent">{html.escape(self._primary_metric_label(summary))}</div>
                    <div class="metric-count">FLAGGED CALLS <strong>{summary.flagged_count} of {summary.evaluated_count}</strong></div>
                  </div>
                  <div class="metric-bar"><div class="metric-bar-fill" style="width: {primary_pct:.1f}%"></div></div>
                  <div class="metric-grid">
                    <div><strong>{html.escape(self._metric_result(summary))}</strong><small>Current result</small></div>
                    <div><strong>{summary.flagged_count}</strong><small>Flagged / positive calls</small></div>
                    <div><strong>{summary.evaluated_count}</strong><small>Evaluated calls</small></div>
                    <div><strong>{html.escape(self._percent(summary.flagged_count, summary.evaluated_count))}</strong><small>Flagged rate</small></div>
                  </div>
                  {delta_markup}
                  <div class="measurement-grid">
                    <div><strong>{html.escape(self._measurement_label(summary))}</strong><small>Measurement standpoint</small></div>
                    <div><strong>{html.escape(self._percent(clear_count, summary.evaluated_count))}</strong><small>Clear / passing rate</small></div>
                  </div>
                  <div class="distribution-bars">
                    <div class="subhead">Metric distribution</div>
                    {self._distribution_bars_html(summary)}
                  </div>
                  <p class="distribution"><strong>Distribution:</strong> {html.escape(self._top_distribution_with_percentages(summary))}</p>
                  <p class="meaning"><strong>Business meaning:</strong> {html.escape(summary.description or "No metric description was configured.")}</p>
                </article>
                """
            )
            metric_cards_by_group.setdefault(summary.group_name, []).append(card)

        quality_panel_markup = ""
        if show_quality_panel:
            quality_groups_markup = []
            for group_name, cards in metric_cards_by_group.items():
                quality_groups_markup.append(
                    f"""
                    <div class="metric-group">
                      <h3 class="metric-group-title">{html.escape(group_name)}</h3>
                      {''.join(cards)}
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
        business_section = ""
        if insight_blocks and show_user_insights:
            business_section = f"""
            <section>
              <!-- 03 Business Insights -->
              <h2>03 User Insights</h2>
              <p class="method">User-insight classifiers emit distributions across operational categories. These are separate from the quality metric panel and are scored during the same per-call evaluation pass.</p>
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
                  <h2>04 User Experience Design Notes</h2>
                  <ol class="design-notes">{notes}</ol>
                </section>
                """

        return f"""
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8" />
          <style>
            @page {{ size: A4; margin: 20mm 16mm; }}
            body {{ font-family: Helvetica, Arial, sans-serif; color: #111827; font-size: 11px; line-height: 1.4; }}
            header {{ border-bottom: 0; padding-bottom: 18px; margin-bottom: 24px; }}
            .brand-header {{ margin-bottom: 22px; }}
            .brand-logo-row {{ display: flex; align-items: center; justify-content: space-between; gap: 42px; min-height: 104px; margin-bottom: 18px; }}
            .brand-logo-slot {{ flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; }}
            .brand-logo-slot-internal {{ align-items: flex-start; }}
            .brand-logo-slot-external {{ align-items: flex-end; text-align: right; }}
            .brand-role {{ color: #7a756d; font-size: 9px; text-transform: uppercase; font-weight: 800; letter-spacing: .12em; }}
            .brand-placeholder {{ color: #9ca3af; border: 1px dashed #d1d5db; border-radius: 8px; padding: 18px 24px; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }}
            .brand-logo {{ max-width: 285px; max-height: 98px; object-fit: contain; }}
            .brand-text {{ margin-top: 4px; font-size: 18px; font-weight: 800; line-height: 1.15; color: #111827; letter-spacing: .18em; text-transform: uppercase; }}
            .title-rule {{ height: 3px; background: #b85f4b; margin: 18px 0 18px; }}
            .eyebrow {{ text-transform: uppercase; letter-spacing: .42em; font-size: 12px; color: #b85f4b; font-weight: 800; margin-bottom: 20px; }}
            .eyebrow .dotsep {{ color: #7a756d; padding: 0 16px; letter-spacing: 0; }}
            .eyebrow .muted {{ color: #7a756d; }}
            h1 {{ font-size: 34px; font-weight: 800; margin: 6px 0; letter-spacing: .1px; }}
            .subtitle {{ font-size: 18px; color: #666; margin-bottom: 16px; }}
            h2 {{ font-size: 18px; margin: 26px 0 10px; color: #0b1220; border-bottom: 2px solid #0b1220; padding-bottom: 2px; }}
            h3 {{ font-size: 13px; margin: 0; }}
            .meta {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }}
            .summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }}
            .metric-group-title {{ font-size: 13px; margin: 12px 0 8px; color: #374151; text-transform: uppercase; letter-spacing: .08em; }}
            .box {{ border: 1px solid #d9dee8; padding: 10px; border-radius: 6px; background: #f7f9fc; }}
            .box strong {{ display: block; font-size: 15px; color: #111827; }}
            .box span {{ color: #667085; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; }}
            .metric {{ break-inside: avoid; border: 1px solid #d9dee8; border-radius: 2px; padding: 12px; margin-bottom: 12px; background: #fff; }}
            .metric-head {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #eef1f5; padding-bottom: 8px; margin-bottom: 8px; }}
            .metric-title {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; font-weight: 800; color: #1f2937; }}
            .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #b85f4b; margin-right: 8px; }}
            .metric-type {{ color: #7a756d; font-size: 10px; text-transform: uppercase; margin-top: 3px; }}
            .direction {{ border: 1px solid #d7cfc2; padding: 7px 10px; color: #7a756d; font-size: 10px; font-weight: 800; align-self: start; }}
            .metric-hero {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; }}
            .metric-percent {{ font-size: 30px; line-height: 1; font-weight: 800; color: #111; }}
            .metric-count {{ color: #7a756d; font-size: 10px; letter-spacing: .04em; font-weight: 800; }}
            .metric-count strong {{ color: #111827; font-size: 13px; letter-spacing: 0; margin-left: 8px; }}
            .metric-bar {{ height: 10px; background: #e7ddd1; border: 1px solid #d7cfc2; margin: 10px 0; }}
            .metric-bar-fill {{ height: 100%; background: #c7725e; }}
            .metric-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
            .metric-grid div {{ background: #f8fafc; border-radius: 6px; padding: 9px 10px; min-height: 48px; }}
            .metric-grid strong, .measurement-grid strong {{ display: block; color: #111827; font-size: 13px; line-height: 1.25; overflow-wrap: anywhere; word-break: normal; }}
            .metric-grid small, .measurement-grid small {{ display: block; margin-top: 4px; color: #667085; font-size: 9px; line-height: 1.2; text-transform: uppercase; letter-spacing: .04em; }}
            .weekly-delta {{ margin-top: 8px; background: #eef6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 9px 10px; }}
            .weekly-delta strong {{ display: block; color: #0f172a; font-size: 14px; }}
            .weekly-delta small {{ display: block; margin-top: 3px; color: #475569; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; }}
            .measurement-grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 8px; margin-top: 8px; }}
            .measurement-grid div {{ background: #fff8f5; border: 1px solid #f3d3c5; border-radius: 6px; padding: 9px 10px; min-height: 48px; }}
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
            .insight-heading {{ display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin-bottom: 6px; }}
            .insight-heading span {{ color: #7a756d; font-size: 10px; font-weight: 700; }}
            .insight-table td:nth-child(2), .insight-table td:nth-child(4) {{ white-space: nowrap; font-weight: 800; }}
            .insight-track {{ height: 9px; background: #e7ddd1; border: 1px solid #d7cfc2; min-width: 120px; }}
            .insight-fill {{ height: 100%; background: #c7725e; }}
            .insight-observation, .insight-evidence {{ margin: 8px 0 0; color: #374151; }}
            .insight-evidence span {{ color: #7a756d; font-size: 9px; margin-left: 6px; }}
            .design-notes {{ margin: 8px 0 0; padding-left: 18px; }}
            .design-notes li {{ margin-bottom: 8px; line-height: 1.5; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
            th, td {{ text-align: left; border-bottom: 1px solid #e5e7eb; padding: 7px; vertical-align: top; }}
            th {{ background: #111827; color: #fff; font-size: 10px; text-transform: uppercase; }}
            .method {{ color: #475467; line-height: 1.5; }}
            .report-footer {{ margin-top: 24px; border-top: 1px solid #1f2937; padding-top: 10px; display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; color: #4b5563; font-size: 10px; }}
            .footer-left, .footer-right {{ display: flex; flex-direction: column; gap: 3px; }}
            .footer-right {{ text-align: right; }}
            .brand-title {{ color: #111827; font-weight: 800; font-size: 11px; letter-spacing: .2px; }}
            .brand-link {{ color: #d16532; font-weight: 700; text-decoration: none; }}
          </style>
        </head>
        <body>
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
              <div class="box"><span>Audit Set</span><strong>{len(metrics)} of {payload.get("total_metric_count") or len(metrics)} metrics</strong></div>
            </div>
          </header>
          {f'''
          <section>
            <h2>01 Audit Summary</h2>
            <p class="method">Quality audit generated from {payload["evaluation"].completed_rows} completed calls across {len(quality_metrics)} quality metrics and {len(business_metrics)} user-insight classifiers.</p>
            <div class="summary">
              <div class="box"><span>Status</span><strong>{html.escape(str(payload["evaluation"].status))}</strong></div>
              <div class="box"><span>Completed</span><strong>{payload["evaluation"].completed_rows}</strong></div>
              <div class="box"><span>Failed</span><strong>{payload["evaluation"].failed_rows}</strong></div>
              <div class="box"><span>Completion</span><strong>{html.escape(payload["completion_rate"])}</strong></div>
            </div>
          </section>
          ''' if show_audit_summary else ''}
          {quality_panel_markup}
          {business_section}
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
              <div>Evaluation ID: {html.escape(str(payload["evaluation"].id))}</div>
              <div>Generated: {html.escape(payload["generated_at_iso"])}</div>
              <div>Call import reports by EfficientAI Cloud</div>
            </div>
          </div>
        </body>
        </html>
        """

    def _render_weasyprint(self, html_content: str) -> bytes | None:
        try:
            from weasyprint import HTML  # type: ignore
        except Exception:
            return None
        try:
            return HTML(string=html_content).write_pdf()
        except Exception as exc:  # pragma: no cover - depends on native libs
            logger.warning("Falling back to basic PDF renderer: {}", exc)
            return None

    def _plain_text_lines(self, payload: dict[str, Any]) -> list[str]:
        metrics: list[MetricReportSummary] = payload["metrics"]
        lines = [
            payload["custom_heading"] or "",
            "QUALITY METRIC AUDIT",
            payload["title"],
            payload["subtitle"],
            f"Client: {payload['vendor_name']}",
            f"Generated: {payload['generated_at']}",
            f"Calls: {payload['evaluation'].total_rows}",
            f"Audit Set: {len(metrics)} metrics",
            "",
            "01 Audit Summary",
            f"Status: {payload['evaluation'].status}",
            f"Completed rows: {payload['evaluation'].completed_rows}",
            f"Failed rows: {payload['evaluation'].failed_rows}",
            f"Completion: {payload['completion_rate']}",
            "",
            "02 Quality Metric Panel",
        ]
        for summary in metrics:
            clear_count = max(summary.evaluated_count - summary.flagged_count, 0)
            metric_lines = [
                f"Metric: {summary.name}",
                f"Type: {summary.metric_type}",
                f"Measurement standpoint: {self._measurement_label(summary)}",
                f"Current result: {self._metric_result(summary)}",
                f"Flagged / positive calls: {summary.flagged_count}",
                f"Evaluated calls: {summary.evaluated_count}",
                f"Flagged rate: {self._percent(summary.flagged_count, summary.evaluated_count)}",
                f"Clear / passing rate: {self._percent(clear_count, summary.evaluated_count)}",
                f"Metric distribution: {self._top_distribution_with_percentages(summary)}",
                f"Business meaning: {summary.description or 'No metric description was configured.'}",
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
        if business_metrics:
            lines.extend(["03 Business Insights"])
            for summary in business_metrics:
                lines.append(
                    f"{summary.name} | n={summary.evaluated_count} | "
                    f"{self._top_distribution_with_percentages(summary)}"
                )
        lines.extend(["04 User Insights / RCA" if business_metrics else "03 User Insights / RCA"])
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
