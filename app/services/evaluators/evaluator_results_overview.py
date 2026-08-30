"""Workspace rollups for evaluator results navigation hub."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import (
    EvaluatorResult,
    Evaluator,
    Agent,
    EvaluatorSuite,
    Scenario,
)
from app.models.schemas import (
    EvaluatorResultCounts,
    EvaluatorResultsAgentSummary,
    EvaluatorResultsOverviewResponse,
    EvaluatorResultsScenarioSummary,
    EvaluatorResultsSuiteSummary,
    EvaluatorResultsUnassignedSummary,
)
from app.services.evaluators.evaluator_results_query import (
    classify_display_status,
    is_in_progress_status,
)


@dataclass
class _MutableCounts:
    total: int = 0
    completed: int = 0
    failed: int = 0
    in_progress: int = 0
    last_run_at: Optional[datetime] = None

    def observe(self, result: EvaluatorResult) -> None:
        self.total += 1
        display = classify_display_status(result)
        if display == "failed":
            self.failed += 1
        elif display == "completed":
            self.completed += 1
        elif is_in_progress_status(display):
            self.in_progress += 1
        ts = result.timestamp
        if ts and (self.last_run_at is None or ts > self.last_run_at):
            self.last_run_at = ts

    def to_schema(self) -> EvaluatorResultCounts:
        return EvaluatorResultCounts(
            total=self.total,
            completed=self.completed,
            failed=self.failed,
            in_progress=self.in_progress,
            last_run_at=self.last_run_at,
        )


def _is_unassigned(result: EvaluatorResult, suite_by_evaluator: Dict[UUID, Optional[UUID]]) -> bool:
    if result.evaluator_id is None:
        return True
    suite_id = suite_by_evaluator.get(result.evaluator_id)
    return suite_id is None


def build_evaluator_results_overview(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: Optional[UUID] = None,
    suite_id: Optional[UUID] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> EvaluatorResultsOverviewResponse:
    query = db.query(EvaluatorResult).filter(
        EvaluatorResult.organization_id == organization_id,
        EvaluatorResult.workspace_id == workspace_id,
        EvaluatorResult.evaluator_id.isnot(None),
    )
    if since is not None:
        query = query.filter(EvaluatorResult.timestamp >= since)
    if until is not None:
        query = query.filter(EvaluatorResult.timestamp <= until)
    rows = query.all()

    evaluator_ids: Set[UUID] = {r.evaluator_id for r in rows if r.evaluator_id}
    evaluators = (
        db.query(Evaluator).filter(Evaluator.id.in_(evaluator_ids)).all()
        if evaluator_ids
        else []
    )
    suite_by_evaluator: Dict[UUID, Optional[UUID]] = {e.id: e.suite_id for e in evaluators}

    suite_ids = {sid for sid in suite_by_evaluator.values() if sid}
    suites = (
        db.query(EvaluatorSuite).filter(EvaluatorSuite.id.in_(suite_ids)).all()
        if suite_ids
        else []
    )
    suite_meta = {s.id: s for s in suites}

    agent_ids = {r.agent_id for r in rows if r.agent_id}
    agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all() if agent_ids else []
    agent_names = {a.id: a.name for a in agents}

    scenario_ids = {r.scenario_id for r in rows if r.scenario_id}
    scenarios = (
        db.query(Scenario).filter(Scenario.id.in_(scenario_ids)).all()
        if scenario_ids
        else []
    )
    scenario_names = {s.id: s.name for s in scenarios}

    workspace_counts = _MutableCounts()
    unassigned_counts = _MutableCounts()
    unassigned_recent: List[str] = []

    agent_counts: Dict[UUID, _MutableCounts] = defaultdict(_MutableCounts)
    suite_counts: Dict[UUID, _MutableCounts] = defaultdict(_MutableCounts)
    scenario_counts: Dict[tuple, _MutableCounts] = defaultdict(_MutableCounts)

    for result in rows:
        workspace_counts.observe(result)
        if _is_unassigned(result, suite_by_evaluator):
            unassigned_counts.observe(result)
            if len(unassigned_recent) < 10:
                unassigned_recent.append(result.result_id)
            if result.agent_id:
                agent_counts[result.agent_id].observe(result)
            continue

        ev_suite_id = suite_by_evaluator.get(result.evaluator_id) if result.evaluator_id else None
        if result.agent_id:
            agent_counts[result.agent_id].observe(result)
        if ev_suite_id:
            suite_counts[ev_suite_id].observe(result)
            if result.scenario_id:
                scenario_counts[(ev_suite_id, result.scenario_id)].observe(result)

    agents_out: List[EvaluatorResultsAgentSummary] = []
    if agent_id is None and suite_id is None:
        for aid, counts in sorted(agent_counts.items(), key=lambda x: agent_names.get(x[0], "")):
            agent_suites: List[EvaluatorResultsSuiteSummary] = []
            for sid, sc in suite_counts.items():
                meta = suite_meta.get(sid)
                if meta and meta.agent_id == aid:
                    scenario_summaries: List[EvaluatorResultsScenarioSummary] = []
                    for (suite_key, scen_id), scen_counts in scenario_counts.items():
                        if suite_key != sid:
                            continue
                        scenario_summaries.append(
                            EvaluatorResultsScenarioSummary(
                                scenario_id=scen_id,
                                scenario_name=scenario_names.get(scen_id, "Scenario"),
                                counts=scen_counts.to_schema(),
                            )
                        )
                    scenario_summaries.sort(key=lambda s: s.scenario_name.lower())
                    agent_suites.append(
                        EvaluatorResultsSuiteSummary(
                            suite_id=sid,
                            suite_name=meta.name,
                            agent_id=meta.agent_id,
                            persona_id=meta.persona_id,
                            counts=sc.to_schema(),
                            scenarios=scenario_summaries or None,
                        )
                    )
            agent_suites.sort(key=lambda s: (s.suite_name or "").lower())
            agents_out.append(
                EvaluatorResultsAgentSummary(
                    agent_id=aid,
                    agent_name=agent_names.get(aid, "Unknown agent"),
                    counts=counts.to_schema(),
                    suites=agent_suites,
                )
            )
    elif agent_id is not None and suite_id is None:
        counts = agent_counts.get(agent_id, _MutableCounts())
        agent_suites = []
        for sid, sc in suite_counts.items():
            meta = suite_meta.get(sid)
            if meta and meta.agent_id == agent_id:
                scenario_summaries = []
                for (suite_key, scen_id), scen_counts in scenario_counts.items():
                    if suite_key != sid:
                        continue
                    scenario_summaries.append(
                        EvaluatorResultsScenarioSummary(
                            scenario_id=scen_id,
                            scenario_name=scenario_names.get(scen_id, "Scenario"),
                            counts=scen_counts.to_schema(),
                        )
                    )
                scenario_summaries.sort(key=lambda s: s.scenario_name.lower())
                agent_suites.append(
                    EvaluatorResultsSuiteSummary(
                        suite_id=sid,
                        suite_name=meta.name,
                        agent_id=meta.agent_id,
                        persona_id=meta.persona_id,
                        counts=sc.to_schema(),
                        scenarios=scenario_summaries or None,
                    )
                )
        agent_suites.sort(key=lambda s: (s.suite_name or "").lower())
        agents_out.append(
            EvaluatorResultsAgentSummary(
                agent_id=agent_id,
                agent_name=agent_names.get(agent_id, "Unknown agent"),
                counts=counts.to_schema(),
                suites=agent_suites,
            )
        )
    elif suite_id is not None:
        meta = suite_meta.get(suite_id)
        aid = meta.agent_id if meta else agent_id
        if aid:
            counts = agent_counts.get(aid, _MutableCounts())
            scenario_summaries: List[EvaluatorResultsScenarioSummary] = []
            for (sid, scen_id), sc in scenario_counts.items():
                if sid != suite_id:
                    continue
                scenario_summaries.append(
                    EvaluatorResultsScenarioSummary(
                        scenario_id=scen_id,
                        scenario_name=scenario_names.get(scen_id, "Scenario"),
                        counts=sc.to_schema(),
                    )
                )
            scenario_summaries.sort(key=lambda s: s.scenario_name.lower())
            suite_summary = EvaluatorResultsSuiteSummary(
                suite_id=suite_id,
                suite_name=meta.name if meta else None,
                agent_id=aid,
                persona_id=meta.persona_id if meta else None,
                counts=suite_counts.get(suite_id, _MutableCounts()).to_schema(),
                scenarios=scenario_summaries,
            )
            agents_out.append(
                EvaluatorResultsAgentSummary(
                    agent_id=aid,
                    agent_name=agent_names.get(aid, "Unknown agent"),
                    counts=counts.to_schema(),
                    suites=[suite_summary],
                )
            )

    return EvaluatorResultsOverviewResponse(
        workspace_counts=workspace_counts.to_schema(),
        agents=agents_out,
        unassigned=EvaluatorResultsUnassignedSummary(
            counts=unassigned_counts.to_schema(),
            recent_result_ids=unassigned_recent,
        ),
    )
