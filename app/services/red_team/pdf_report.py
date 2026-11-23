"""PDF report for a red team run: verdict, category grids and breached-attack evidence.

Reuses the call-import report's WeasyPrint renderer, stylesheet and plain-text fallback.
Harmful agent text in violence / illegal-activity categories is withheld.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.database import Agent, RedTeamAttack, RedTeamRun
from app.services.red_team.report import (
    build_report,
    category_name,
    redacted_transcript,
    technique_name,
)
from app.services.reporting.call_import_evaluation_pdf_report import (
    CallImportEvaluationPdfReportService,
)

VERDICT_LABELS = {
    "breached": "Breached",
    "held_under_pressure": "Held under pressure",
    "held": "Held",
    "inconclusive": "Inconclusive",
}
_STATUS_COLORS = {"FAIL": "#b42318", "PARTIAL": "#b54708", "PASS": "#067647", "NOT_TESTED": "#667085"}
_MAX_EVIDENCE_ATTACKS = 15
_MAX_TURNS_PER_ATTACK = 16

_EXTRA_CSS = """
.rt-chip { display:inline-block; padding:1px 6px; border-radius:4px; color:#fff; font-size:9pt; font-weight:600; }
.rt-verdict { font-size:18pt; font-weight:700; margin:4px 0 8px; }
.rt-turn { margin:2px 0; font-size:9pt; }
.rt-turn.evidence { background:#fef3f2; }
.rt-role { font-weight:600; }
.rt-attack { page-break-inside: avoid; margin-bottom:12px; }
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _chip(status: str) -> str:
    return f'<span class="rt-chip" style="background:{_STATUS_COLORS.get(status, "#667085")}">{_e(status)}</span>'


class _Renderer(CallImportEvaluationPdfReportService):
    def render(self, run: RedTeamRun, agent: Optional[Agent], attacks: list[RedTeamAttack]) -> bytes:
        report = run.report if isinstance(run.report, dict) else build_report(run, attacks)
        html_doc = self._html(run, agent, attacks, report)
        pdf = self._render_weasyprint(html_doc, label=f"red team {run.run_id}")
        if pdf is not None:
            return pdf
        return self._render_basic_pdf(self._lines(run, agent, report))

    def _html(self, run: RedTeamRun, agent: Optional[Agent], attacks: list[RedTeamAttack], report: dict[str, Any]) -> str:
        totals = report.get("totals") or {}
        verdict = VERDICT_LABELS.get(report.get("verdict") or "", "Inconclusive")
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        knowledge = ", ".join(_e(k.get("label")) for k in (run.attacker_knowledge or []) if isinstance(k, dict)) or "none"

        def _category_rows(kind: str) -> str:
            rows = []
            for c in report.get("categories") or []:
                if c.get("kind") != kind:
                    continue
                rows.append(
                    f"<tr><td>{_e(c['id'] if kind == 'owasp' else '')} {_e(c.get('name'))}</td>"
                    f"<td>{_chip(c.get('status', 'NOT_TESTED'))}</td>"
                    f"<td class='fd-col-num'>{_e(c.get('attacks'))}</td>"
                    f"<td class='fd-col-num'>{_e(c.get('breached'))}</td>"
                    f"<td class='fd-col-num'>{_e(c.get('conceded'))}</td></tr>"
                )
            return "".join(rows)

        table_head = "<tr><th>Category</th><th>Result</th><th>Attacks</th><th>Breached</th><th>Conceded</th></tr>"
        by_id = {str(a.id): a for a in attacks}
        evidence_ids = (report.get("breached_attack_ids") or []) + (report.get("conceded_attack_ids") or [])
        evidence = []
        for attack_id in evidence_ids[:_MAX_EVIDENCE_ATTACKS]:
            attack = by_id.get(attack_id)
            if attack is None:
                continue
            judge = attack.judge if isinstance(attack.judge, dict) else {}
            marked = set(judge.get("evidence_turns") or [])
            turns = []
            for index, entry in enumerate(redacted_transcript(attack)[:_MAX_TURNS_PER_ATTACK]):
                role = "Attacker" if entry.get("role") == "attacker" else "Agent"
                css = "rt-turn evidence" if index in marked else "rt-turn"
                turns.append(f"<div class='{css}'><span class='rt-role'>{role}:</span> {_e(entry.get('text'))}</div>")
            leaked = "; ".join(judge.get("leaked_data") or []) or "—"
            actions = "; ".join(judge.get("gated_actions") or []) or "—"
            evidence.append(
                f"""<div class="rt-attack">
                  <h3>{_e(technique_name(attack.technique_id) or attack.technique_id)} · {_e(category_name(attack))} · {_e((attack.outcome or '').upper())}</h3>
                  <p class="method"><b>Goal:</b> {_e(attack.goal)}<br/><b>Judge:</b> {_e(judge.get('rationale'))}<br/>
                  <b>Disclosed:</b> {_e(leaked)}<br/><b>Gated actions:</b> {_e(actions)}</p>
                  {''.join(turns)}
                </div>"""
            )
        family_rows = "".join(
            f"<tr><td>{_e(f.get('name'))}</td><td class='fd-col-num'>{_e(f.get('attempts'))} / {_e(f.get('quota'))}</td>"
            f"<td class='fd-col-num'>{_e(f.get('breached'))}</td><td class='fd-col-num'>{_e(f.get('conceded'))}</td></tr>"
            for f in report.get("families") or []
        )
        profile = run.agent_profile if isinstance(run.agent_profile, dict) else {}
        harm_note = (
            "<p class='method'><b>A content-harm failure alone fails the run.</b></p>"
            if report.get("content_harm_failed")
            else ""
        )
        return f"""<!doctype html><html><head><meta charset="utf-8"/>
        <style>{self._report_css()}{_EXTRA_CSS}</style></head><body>
        <section class="report-section">
          <h1>Red team report · {_e(run.name or (agent.name if agent else ''))}</h1>
          <p class="method">Agent: {_e(agent.name if agent else run.agent_id)} · Run {_e(run.run_id)} · Intensity {_e(run.intensity)} · {_e(run.modality)}
          · Catalog {_e(run.catalog_version)} · Attacker knowledge: {knowledge} · Generated {generated}</p>
          <div class="rt-verdict">{_e(verdict)}{' — PASS' if report.get('passed') else ' — FAIL'}</div>
          <p class="method">{_e(totals.get('attacks'))} attacks: {_e(totals.get('breached'))} breached, {_e(totals.get('conceded'))} conceded ground,
          {_e(totals.get('held'))} held, {_e(totals.get('errors'))} could not be scored. {_e(totals.get('recon'))} discovery conversations.</p>
          {harm_note}
        </section>
        <section class="report-section"><h2>OWASP LLM Top 10</h2>
          <table class="insight-table fd-summary-table">{table_head}{_category_rows('owasp')}</table>
          <p class="method">LLM03 and LLM10 do not apply to a customer-service agent. NOT_TESTED categories did not run; use a higher intensity to cover them.</p>
        </section>
        <section class="report-section"><h2>Content harm (MLCommons AILuminate)</h2>
          <table class="insight-table fd-summary-table">{table_head}{_category_rows('harm')}</table>
        </section>
        <section class="report-section"><h2>Attack families</h2>
          <table class="insight-table fd-summary-table"><tr><th>Family</th><th>Attempts / quota</th><th>Breached</th><th>Conceded</th></tr>{family_rows}</table>
        </section>
        <section class="report-section"><h2>What recon learned</h2>
          <p class="method">{_e(profile.get('summary'))}</p>
          <p class="method"><b>Data held:</b> {_e('; '.join(profile.get('data_held') or []) or '—')}<br/>
          <b>Gated actions:</b> {_e('; '.join(profile.get('gated_actions') or []) or '—')}<br/>
          <b>Verification:</b> {_e('; '.join(profile.get('verification_steps') or []) or '—')}</p>
        </section>
        <section class="report-section"><h2>Breaches and conceded ground</h2>
          {''.join(evidence) or "<p class='method'>No attack breached the agent or made it concede ground.</p>"}
        </section>
        </body></html>"""

    def _lines(self, run: RedTeamRun, agent: Optional[Agent], report: dict[str, Any]) -> list[str]:
        totals = report.get("totals") or {}
        lines = [
            f"Red team report - run {run.run_id}",
            f"Agent: {agent.name if agent else run.agent_id}",
            f"Verdict: {VERDICT_LABELS.get(report.get('verdict') or '', 'Inconclusive')}",
            f"Attacks: {totals.get('attacks')} (breached {totals.get('breached')}, conceded {totals.get('conceded')}, held {totals.get('held')})",
            "",
        ]
        for c in report.get("categories") or []:
            lines.append(f"{c.get('id')} {c.get('name')}: {c.get('status')}")
        return lines


def render_red_team_pdf(*, run: RedTeamRun, agent: Optional[Agent], attacks: list[RedTeamAttack]) -> bytes:
    return _Renderer().render(run, agent, attacks)
