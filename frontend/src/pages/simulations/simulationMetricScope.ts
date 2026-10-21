import {
  getTopLevelMetricsForAgentMedium,
  normalizeSelectedMetricIds,
  type MetricRow,
} from '../evaluators/components/metricSelectionUtils'

export function isGoldenMetric(metric: MetricRow): boolean {
  return !metric.agent_ids?.length && !metric.scenario_ids?.length
}

export function agentLinkedMetrics(metrics: MetricRow[]): MetricRow[] {
  return getTopLevelMetricsForAgentMedium(metrics, 'voice').filter(
    (m) => (m.agent_ids?.length ?? 0) > 0,
  )
}

export function scenarioLinkedMetrics(metrics: MetricRow[]): MetricRow[] {
  return getTopLevelMetricsForAgentMedium(metrics, 'voice').filter(
    (m) => (m.scenario_ids?.length ?? 0) > 0,
  )
}

export function goldenMetrics(metrics: MetricRow[], agentMedium: 'voice' | 'chat'): MetricRow[] {
  return getTopLevelMetricsForAgentMedium(metrics, agentMedium).filter(isGoldenMetric)
}

export function agentMetricsForRun(
  metrics: MetricRow[],
  agentMedium: 'voice' | 'chat',
  runAgentId: string,
): MetricRow[] {
  return getTopLevelMetricsForAgentMedium(metrics, agentMedium).filter((m) => {
    const links = m.agent_ids || []
    return links.length > 0 && links.includes(runAgentId)
  })
}

export function scenarioMetricsForRun(
  metrics: MetricRow[],
  agentMedium: 'voice' | 'chat',
  selectedScenarioIds: string[],
): MetricRow[] {
  const selected = new Set(selectedScenarioIds)
  return getTopLevelMetricsForAgentMedium(metrics, agentMedium).filter((m) => {
    const links = m.scenario_ids || []
    return links.length > 0 && links.some((id) => selected.has(id))
  })
}

/** One list for the sim run picker: agent scope ok and useful for at least one selected scenario. */
export function metricsForSimulationRun(
  metrics: MetricRow[],
  agentMedium: 'voice' | 'chat',
  runAgentId: string,
  selectedScenarioIds: string[],
): MetricRow[] {
  const selectedScenarios = new Set(selectedScenarioIds)
  const top = getTopLevelMetricsForAgentMedium(metrics, agentMedium)
  const out = top.filter((m) => {
    const agentLinks = m.agent_ids || []
    if (agentLinks.length > 0 && !agentLinks.includes(runAgentId)) return false
    const scenarioLinks = m.scenario_ids || []
    if (scenarioLinks.length === 0) return true
    if (selectedScenarios.size === 0) return false
    return scenarioLinks.some((id) => selectedScenarios.has(id))
  })
  return out.sort((a, b) => a.name.localeCompare(b.name))
}

export function metricAppliesToTrial(
  metric: MetricRow,
  agentId: string,
  scenarioId: string,
): boolean {
  const agentLinks = metric.agent_ids || []
  const scenarioLinks = metric.scenario_ids || []
  const agentOk = agentLinks.length === 0 || agentLinks.includes(agentId)
  const scenarioOk = scenarioLinks.length === 0 || scenarioLinks.includes(scenarioId)
  return agentOk && scenarioOk
}

export function scenariosWithNoApplicableMetrics(
  scenarios: Array<{ id: string; name: string }>,
  metrics: MetricRow[],
  agentMedium: 'voice' | 'chat',
  selectedMetricIds: string[],
  runAgentId: string,
): string[] {
  const normalized = new Set(selectedMetricIds)
  const top = getTopLevelMetricsForAgentMedium(metrics, agentMedium)
  return scenarios
    .filter((s) => {
      const applicable = top.some(
        (m) => normalized.has(m.id) && metricAppliesToTrial(m, runAgentId, s.id),
      )
      return !applicable
    })
    .map((s) => s.name)
}

export function syncSimulationMetricSelection(
  prev: string[],
  metricRows: MetricRow[],
  agentMedium: 'voice' | 'chat',
  runAgentId: string,
  scenarioIds: string[],
  goldenOptOut: Set<string>,
  addedScenarioIds: string[],
): string[] {
  const next = new Set(normalizeSelectedMetricIds(prev, metricRows))
  const selectedScenarios = new Set(scenarioIds)

  for (const m of getTopLevelMetricsForAgentMedium(metricRows, agentMedium)) {
    const agentLinks = m.agent_ids || []
    const scenarioLinks = m.scenario_ids || []

    if (agentLinks.length === 0 && scenarioLinks.length === 0) {
      if (!goldenOptOut.has(m.id)) next.add(m.id)
      continue
    }

    if (agentLinks.length > 0) {
      if (!agentLinks.includes(runAgentId)) {
        next.delete(m.id)
        continue
      }
      if (agentLinks.includes(runAgentId)) {
        next.add(m.id)
      }
    }

    if (scenarioLinks.length > 0) {
      const applies = scenarioLinks.some((sid) => selectedScenarios.has(sid))
      if (!applies) {
        next.delete(m.id)
        continue
      }
      if (scenarioLinks.some((sid) => addedScenarioIds.includes(sid))) {
        next.add(m.id)
      }
    }
  }

  return normalizeSelectedMetricIds(Array.from(next), metricRows)
}

export function formatMetricScopeLabel(
  metric: MetricRow,
  scenarioNameById: Map<string, string>,
  agentNameById?: Map<string, string>,
): string {
  const parts: string[] = []
  if (metric.agent_ids?.length) {
    const names = metric.agent_ids
      .map((id) => agentNameById?.get(id) || id.slice(0, 8))
      .join(', ')
    parts.push(`Agents: ${names || 'selected'}`)
  }
  if (metric.scenario_ids?.length) {
    const names = metric.scenario_ids
      .map((id) => scenarioNameById.get(id) || id.slice(0, 8))
      .join(', ')
    parts.push(`Scenarios: ${names || 'selected'}`)
  }
  if (parts.length === 0) return 'All agents & scenarios'
  return parts.join(' · ')
}
