"""PDF report for a Harbor simulation run: KPIs, failure diagnostics and prompt fixes.

Reuses the call-import report's stylesheet, failure-diagnostics and prompt-improvement
sections so both reports read the same.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from app.models.database import Agent, SimulationRun
from app.services.reporting.call_import_evaluation_pdf_report import (
    CallImportEvaluationPdfReportService,
)

_COMBO_ROWS_MAX = 25


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _num(value: Any) -> str:
    if value is None:
        return "—"
    return html.escape(str(value))


class SimulationRunPdfReportService(CallImportEvaluationPdfReportService):
    def _evaluation_call_deep_link(
        self,
        *,
        platform_base_url: str | None,
        call_import_id: str,
        evaluation_id: str,
        conversation_id: str | None,
        evaluation_row_id: str | None = None,
    ) -> str | None:
        # ``evaluation_id`` carries the run's 6-digit ID; evidence rows are trial IDs.
        del call_import_id, conversation_id
        base = (platform_base_url or "").strip().rstrip("/")
        if not base or not evaluation_row_id:
            return None
        return (
            f"{base}/simulations/{evaluation_id}?tab=analysis"
            f"&trial={quote(str(evaluation_row_id), safe='')}"
        )

    def render_pdf(
        self,
        *,
        run: SimulationRun,
        agent: Agent,
        summary: dict[str, Any],
        success_rules: dict[str, str],
        metric_clusters: Optional[dict[str, Any]],
        prompt_improvements: Optional[dict[str, Any]],
        sections: Optional[dict[str, bool]] = None,
        platform_base_url: Optional[str] = None,
        generated_at: Optional[datetime] = None,
    ) -> bytes:
        payload = {
            "run": run,
            "agent": agent,
            "summary": summary or {},
            "success_rules": success_rules or {},
            "metric_clusters": metric_clusters,
            "prompt_improvements": prompt_improvements,
            "sections": sections or {},
            "platform_base_url": platform_base_url,
            "generated_at_iso": (generated_at or datetime.now(timezone.utc)).strftime(
                "%Y-%m-%d %H:%M UTC"
            ),
        }
        pdf_bytes = self._render_weasyprint(
            self._render_simulation_html(payload),
            label=f"simulation run {run.run_id}",
        )
        if pdf_bytes is not None:
            return pdf_bytes
        return self._render_basic_pdf(self._simulation_plain_text_lines(payload))

    def _run_title(self, run: SimulationRun, agent: Agent) -> str:
        return run.name or f"{agent.name} · run {run.run_id}"

    def _llm_label(self, run: SimulationRun, side: str) -> str:
        llms = run.resolved_llms if isinstance(run.resolved_llms, dict) else {}
        entry = llms.get(side)
        if not isinstance(entry, dict):
            return "Not resolved"
        label = str(entry.get("label") or "")
        source = str(entry.get("source_label") or "")
        return f"{label} ({source})" if source else label

    def _kpi_cards(self, summary: dict[str, Any]) -> list[tuple[str, str]]:
        uses_criteria = bool(summary.get("uses_success_criteria"))
        cards = [
            ("Pass rate", _pct(summary.get("pass_rate"))),
            ("Criteria met" if uses_criteria else "Mean score", _pct(summary.get("mean_reward"))),
            ("Consistency (pass^k)", _pct(summary.get("pass_all_rate"))),
            ("Pass@k", _pct(summary.get("pass_any_rate"))),
            ("Errored trials", _num(summary.get("n_failed") or 0)),
            ("Avg turns", _num(summary.get("avg_turns"))),
        ]
        tools = summary.get("tools")
        if isinstance(tools, dict) and tools.get("total_calls"):
            cards.append(("Tool calls succeeded", _pct(tools.get("success_rate"))))
        return cards

    def _run_summary_section_html(self, payload: dict[str, Any]) -> str:
        summary = payload["summary"]
        cards = "".join(
            f"""
            <div class="audit-stat-card">
              <div class="audit-stat-rule"></div>
              <div class="audit-stat-label">{html.escape(label.upper())}</div>
              <div class="audit-stat-value">{value}</div>
            </div>
            """
            for label, value in self._kpi_cards(summary)
        )
        run: SimulationRun = payload["run"]
        n_completed = int(summary.get("n_completed") or 0)
        n_passed = int(summary.get("n_passed") or 0)
        verdict = (
            f"{n_passed} of {n_completed} completed trials met every success rule"
            if summary.get("uses_success_criteria")
            else f"{n_passed} of {n_completed} completed trials scored at or above "
            f"the {run.pass_threshold:.2f} pass threshold"
        )
        return f"""
          <section class="audit-summary-section report-section">
            <h2>01 Run Summary</h2>
            <div class="audit-summary method"><p>{html.escape(verdict)}.
              Production agent: <strong>{html.escape(self._llm_label(run, "production"))}</strong>.
              Simulated caller: <strong>{html.escape(self._llm_label(run, "test"))}</strong>.</p></div>
            <div class="audit-stat-strip">{cards}</div>
          </section>
        """

    def _metric_results_section_html(self, payload: dict[str, Any]) -> str:
        summary = payload["summary"]
        rules: dict[str, str] = payload["success_rules"]
        metrics = [m for m in summary.get("metrics") or [] if isinstance(m, dict)]
        if not metrics:
            return ""
        uses_criteria = bool(summary.get("uses_success_criteria"))
        rows = "".join(
            f"""
            <tr>
              <td>{html.escape(str(m.get("name") or "Metric"))}</td>
              <td>{html.escape(rules.get(str(m.get("metric_id")), "—"))}</td>
              <td class="fd-col-num">{_pct(m.get("pass_rate") if uses_criteria else m.get("mean"))}</td>
              <td class="fd-col-num">{_num(m.get("n"))}</td>
            </tr>
            """
            for m in metrics
        )
        value_header = "Pass rate" if uses_criteria else "Mean score"
        intro = (
            "Each trial is judged against the success rule set for every metric when the run "
            "started. Metrics are sorted from weakest to strongest."
            if uses_criteria
            else "No success rules were set for this run; metrics show the mean normalised score."
        )
        return f"""
          <section class="report-section">
            <h2>02 Success Rules &amp; Metric Results</h2>
            <p class="method">{intro}</p>
            <table class="insight-table fd-summary-table">
              <thead><tr><th>Metric</th><th>Success rule</th><th>{value_header}</th><th>Trials</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </section>
        """

    def _scenario_results_section_html(self, payload: dict[str, Any]) -> str:
        combos = [c for c in payload["summary"].get("combos") or [] if isinstance(c, dict)]
        if not combos:
            return ""
        rows = "".join(
            f"""
            <tr>
              <td>{html.escape(str(c.get("scenario_name") or "Scenario"))}</td>
              <td>{html.escape(str(c.get("persona_name") or "Persona"))}</td>
              <td class="fd-col-num">{_num(c.get("passed"))} / {_num(c.get("attempts"))}</td>
              <td class="fd-col-num">{_pct(c.get("mean_reward"))}</td>
            </tr>
            """
            for c in combos[:_COMBO_ROWS_MAX]
        )
        more = (
            f'<p class="method">Showing the {_COMBO_ROWS_MAX} weakest of {len(combos)} combinations.</p>'
            if len(combos) > _COMBO_ROWS_MAX
            else ""
        )
        return f"""
          <section class="report-section">
            <h2>03 Scenario Results</h2>
            <p class="method">Scenario × persona combinations, weakest first.</p>
            <table class="insight-table fd-summary-table">
              <thead><tr><th>Scenario</th><th>Persona</th><th>Passed</th><th>Mean score</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
            {more}
          </section>
        """

    def _render_simulation_html(self, payload: dict[str, Any]) -> str:
        run: SimulationRun = payload["run"]
        agent: Agent = payload["agent"]
        summary = payload["summary"]
        sections = payload["sections"]

        run_summary = (
            self._run_summary_section_html(payload)
            + self._metric_results_section_html(payload)
            + self._scenario_results_section_html(payload)
            if sections.get("run_summary", True)
            else ""
        )

        failure_diagnostics = ""
        clusters = payload.get("metric_clusters")
        if (
            sections.get("failure_diagnostics", True)
            and isinstance(clusters, dict)
            and clusters.get("status") == "completed"
        ):
            failure_diagnostics = self._failure_diagnostics_section_html(
                clusters,
                clusters.get("overview"),
                platform_base_url=payload.get("platform_base_url"),
                evaluation_id=run.run_id,
            )

        prompt_section = ""
        improvements = payload.get("prompt_improvements")
        if (
            sections.get("prompt_improvements", True)
            and isinstance(improvements, dict)
            and improvements.get("status") == "completed"
        ):
            prompt_section = self._prompt_improvements_section_html(improvements).replace(
                ", aligned with the Visualizations → Prompt / Agent Improvements view.",
                ", based on the failure clusters above.",
            )

        methodology = (
            """
          <section class="report-section methodology-section">
            <p class="method">This report is generated from a simulation run: a test agent played
            each scenario × persona against the production agent, and an LLM judge scored every
            trial. A metric counts as failed in a trial when it missed the success rule set for the
            run. Failed trials are clustered by an LLM into failure patterns with engineering gap
            labels, and prompt recommendations target the largest clusters.</p>
          </section>
            """
            if sections.get("methodology", True)
            else ""
        )

        meta_boxes = [
            ("Agent", html.escape(agent.name or "Agent")),
            ("Run", html.escape(run.run_id)),
            ("Trials", _num(summary.get("n_trials") or run.expected_trials)),
            ("Scenarios", _num(len(run.scenario_ids or []))),
            ("Personas", _num(len(run.persona_ids or []))),
        ]
        meta = "".join(
            f'<div class="box"><span>{label}</span><strong>{value}</strong></div>'
            for label, value in meta_boxes
        )
        return f"""
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8" />
          <style>
{self._report_css()}
          </style>
        </head>
        <body class="report-body internal-report">
          <header>
            <div class="eyebrow">Simulation Run Report <span class="dotsep">·</span> <span class="muted">{html.escape(run.status)}</span></div>
            <div class="title-rule"></div>
            <h1>{html.escape(self._run_title(run, agent))}</h1>
            <div class="subtitle">Simulation results, failure diagnostics and prompt recommendations</div>
            <div class="meta">{meta}</div>
          </header>
          {run_summary}
          {failure_diagnostics}
          {prompt_section}
          {methodology}
          <div class="report-footer">
            <div class="footer-left">
              <div class="brand-title">Powered by EfficientAI</div>
              <div>Voice AI Evaluation Platform</div>
              <div>Website: <a href="https://efficientai.cloud" class="brand-link">https://efficientai.cloud</a></div>
            </div>
            <div class="footer-right">
              <div>Simulation run: {html.escape(run.run_id)}</div>
              <div>Generated: {html.escape(payload["generated_at_iso"])}</div>
            </div>
          </div>
        </body>
        </html>
        """

    def _simulation_plain_text_lines(self, payload: dict[str, Any]) -> list[str]:
        run: SimulationRun = payload["run"]
        agent: Agent = payload["agent"]
        summary = payload["summary"]
        lines = [
            "SIMULATION RUN REPORT",
            self._run_title(run, agent),
            f"Agent: {agent.name}",
            f"Run: {run.run_id}",
            f"Generated: {payload['generated_at_iso']}",
            "",
            "01 Run Summary",
        ]
        lines.extend(f"{label}: {html.unescape(value)}" for label, value in self._kpi_cards(summary))
        lines.extend(["", "02 Success Rules & Metric Results"])
        for m in summary.get("metrics") or []:
            if isinstance(m, dict):
                rule = payload["success_rules"].get(str(m.get("metric_id")), "-")
                lines.append(f"{m.get('name')}: {_pct(m.get('mean'))} (rule: {rule})")
        clusters = payload.get("metric_clusters")
        if isinstance(clusters, dict) and clusters.get("status") == "completed":
            lines.extend(["", "04 Failure Diagnostics"])
            for group in clusters.get("groups") or []:
                if not isinstance(group, dict):
                    continue
                lines.append(f"{group.get('metric_name')}: {group.get('flagged_count')} flagged")
                for cluster in group.get("clusters") or []:
                    if isinstance(cluster, dict):
                        lines.append(f"  - {cluster.get('label')} ({cluster.get('count')})")
        improvements = payload.get("prompt_improvements")
        if isinstance(improvements, dict) and improvements.get("status") == "completed":
            lines.extend(["", "05 Prompt Improvement Recommendations"])
            for item in improvements.get("suggestions") or []:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('target_section') or item.get('metric_name')}")
                    lines.append(f"  {item.get('suggested_text') or ''}")
        return lines


simulation_run_pdf_report_service = SimulationRunPdfReportService()
