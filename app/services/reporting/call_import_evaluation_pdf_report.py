"""PDF report rendering for Call Import evaluation results."""

from __future__ import annotations

import html
import io
import math
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    ) -> bytes:
        generated_at = generated_at or datetime.now(timezone.utc)
        summaries = self._summarize_metrics(metrics, rows)
        title = "Internal Quality Metric Audit" if internal else "Quality Metric Audit"
        payload = {
            "title": title,
            "vendor_name": vendor_name,
            "generated_at": generated_at.strftime("%b %d, %Y %H:%M UTC"),
            "call_import": call_import,
            "evaluation": evaluation,
            "metrics": summaries,
            "rows": rows,
            "internal": internal,
            "completion_rate": self._percent(
                evaluation.completed_rows, evaluation.total_rows
            ),
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

    def _metric_result(self, summary: MetricReportSummary) -> str:
        if summary.numeric_values:
            avg = sum(summary.numeric_values) / len(summary.numeric_values)
            return f"Average {avg:.2f}"
        return self._top_distribution(summary)

    def _render_html(self, payload: dict[str, Any]) -> str:
        metrics: list[MetricReportSummary] = payload["metrics"]
        rows: list[tuple[CallImportEvaluationRow, CallImportRow]] = payload["rows"]
        internal = bool(payload["internal"])
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

        metric_cards = []
        for summary in metrics:
            metric_cards.append(
                f"""
                <article class="metric">
                  <div class="metric-head">
                    <h3>{html.escape(summary.name)}</h3>
                    <span>{html.escape(summary.metric_type)}</span>
                  </div>
                  <div class="metric-grid">
                    <div><strong>{html.escape(self._metric_result(summary))}</strong><small>Current result</small></div>
                    <div><strong>{summary.flagged_count}</strong><small>Flagged / positive calls</small></div>
                    <div><strong>{summary.evaluated_count}</strong><small>Evaluated calls</small></div>
                    <div><strong>{html.escape(self._percent(summary.flagged_count, summary.evaluated_count))}</strong><small>Flagged rate</small></div>
                  </div>
                  <p>{html.escape(summary.description or "No metric description was configured.")}</p>
                </article>
                """
            )

        diagnostics = ""
        if internal:
            diagnostic_rows = []
            for eval_row, source_row in rows[:25]:
                diagnostic_rows.append(
                    f"""
                    <tr>
                      <td>{source_row.row_index}</td>
                      <td>{html.escape(source_row.conversation_id)}</td>
                      <td>{html.escape(str(eval_row.status))}</td>
                      <td>{html.escape(str(eval_row.id))}</td>
                      <td>{html.escape(payload["evaluation"].transcript_source or "production")}</td>
                    </tr>
                    """
                )
            diagnostics = f"""
            <section>
              <h2>Internal Diagnostics</h2>
              <table>
                <thead><tr><th>Row</th><th>Conversation ID</th><th>Status</th><th>Evaluation Row ID</th><th>Transcript Source</th></tr></thead>
                <tbody>{''.join(diagnostic_rows)}</tbody>
              </table>
            </section>
            """

        return f"""
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8" />
          <style>
            @page {{ size: A4; margin: 28px; }}
            body {{ font-family: Inter, Arial, sans-serif; color: #172033; font-size: 12px; }}
            header {{ border-bottom: 3px solid #172033; padding-bottom: 18px; margin-bottom: 24px; }}
            .eyebrow {{ text-transform: uppercase; letter-spacing: .12em; font-size: 10px; color: #586174; }}
            h1 {{ font-size: 30px; margin: 6px 0; }}
            h2 {{ font-size: 16px; margin: 24px 0 10px; color: #172033; }}
            h3 {{ font-size: 13px; margin: 0; }}
            .meta, .summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }}
            .box {{ border: 1px solid #d9dee8; padding: 10px; border-radius: 6px; background: #f7f9fc; }}
            .box strong {{ display: block; font-size: 15px; color: #111827; }}
            .box span, small {{ color: #667085; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; }}
            .metric {{ break-inside: avoid; border: 1px solid #d9dee8; border-radius: 8px; padding: 12px; margin-bottom: 10px; }}
            .metric-head {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #eef1f5; padding-bottom: 8px; margin-bottom: 8px; }}
            .metric-head span {{ color: #475467; font-size: 10px; text-transform: uppercase; }}
            .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
            .metric-grid div {{ background: #f8fafc; border-radius: 6px; padding: 8px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
            th, td {{ text-align: left; border-bottom: 1px solid #e5e7eb; padding: 7px; vertical-align: top; }}
            th {{ background: #f3f4f6; font-size: 10px; text-transform: uppercase; color: #475467; }}
            .method {{ color: #475467; line-height: 1.5; }}
          </style>
        </head>
        <body>
          <header>
            <div class="eyebrow">Quality Metric Audit</div>
            <h1>{html.escape(payload["title"])}</h1>
            <div class="meta">
              <div class="box"><span>Client</span><strong>{html.escape(payload["vendor_name"])}</strong></div>
              <div class="box"><span>Generated</span><strong>{html.escape(payload["generated_at"])}</strong></div>
              <div class="box"><span>Calls</span><strong>{payload["evaluation"].total_rows}</strong></div>
              <div class="box"><span>Audit Set</span><strong>{len(metrics)} metrics</strong></div>
            </div>
          </header>
          <section>
            <h2>01 Audit Summary</h2>
            <div class="summary">
              <div class="box"><span>Status</span><strong>{html.escape(str(payload["evaluation"].status))}</strong></div>
              <div class="box"><span>Completed</span><strong>{payload["evaluation"].completed_rows}</strong></div>
              <div class="box"><span>Failed</span><strong>{payload["evaluation"].failed_rows}</strong></div>
              <div class="box"><span>Completion</span><strong>{html.escape(payload["completion_rate"])}</strong></div>
            </div>
          </section>
          <section>
            <h2>02 Quality Metric Panel</h2>
            {''.join(metric_cards)}
          </section>
          <section>
            <h2>03 User Insights / RCA</h2>
            <table>
              <thead><tr><th>Metric</th><th>Example call</th><th>Evidence / rationale</th></tr></thead>
              <tbody>{''.join(evidence_rows)}</tbody>
            </table>
          </section>
          {diagnostics}
          <section>
            <h2>Methodology</h2>
            <p class="method">This report is generated from completed Call Import evaluation results. Metrics are derived from the saved evaluation outputs and the transcript source configured for the run. External reports omit internal row identifiers and diagnostic metadata; internal reports include operational details for QA review.</p>
          </section>
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
        rows: list[tuple[CallImportEvaluationRow, CallImportRow]] = payload["rows"]
        internal = bool(payload["internal"])
        lines = [
            "QUALITY METRIC AUDIT",
            payload["title"],
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
            lines.extend(
                [
                    f"Metric: {summary.name}",
                    f"Type: {summary.metric_type}",
                    f"Current result: {self._metric_result(summary)}",
                    f"Flagged / positive calls: {summary.flagged_count}",
                    f"Evaluated calls: {summary.evaluated_count}",
                    f"Business meaning: {summary.description or 'No metric description was configured.'}",
                    "",
                ]
            )
        lines.extend(["03 User Insights / RCA"])
        has_rationale = False
        for summary in metrics:
            for call_id, rationale in summary.rationales[:4]:
                has_rationale = True
                lines.append(f"{summary.name} | {call_id} | {rationale}")
        if not has_rationale:
            lines.append("No flagged-call rationales were captured for this run.")
        if internal:
            lines.extend(["", "Internal Diagnostics"])
            for eval_row, source_row in rows[:25]:
                lines.append(
                    f"Row {source_row.row_index} | Conversation ID {source_row.conversation_id} | "
                    f"Status {eval_row.status} | Evaluation Row ID {eval_row.id} | "
                    f"Transcript Source {payload['evaluation'].transcript_source or 'production'}"
                )
        lines.extend(
            [
                "",
                "Methodology",
                "This report is generated from completed Call Import evaluation results. "
                "Metrics are derived from saved evaluation outputs and the transcript source configured for the run.",
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
