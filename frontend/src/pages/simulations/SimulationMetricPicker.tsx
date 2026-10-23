import { useMemo } from 'react'
import { Layers } from 'lucide-react'
import {
  getEnabledChildren,
  isCategorizationParent,
  normalizeSelectedMetricIds,
  toggleMetricSelection,
  type MetricRow,
} from '../evaluators/components/metricSelectionUtils'
import {
  agentMetricsForRun,
  formatMetricScopeLabel,
  goldenMetrics,
  isGoldenMetric,
  scenarioMetricsForRun,
} from './simulationMetricScope'

interface Props {
  metricRows: MetricRow[]
  agentMedium: 'voice' | 'chat'
  runAgentId: string
  selectedScenarioIds: string[]
  scenarioNameById: Map<string, string>
  agentNameById?: Map<string, string>
  selectedMetricIds: string[]
  goldenOptOut: Set<string>
  onGoldenOptOutChange: (next: Set<string>) => void
  onChange: (ids: string[]) => void
}

function MetricCheckboxRow({
  metric,
  checked,
  hint,
  onToggle,
}: {
  metric: MetricRow
  checked: boolean
  hint?: string
  onToggle: () => void
}) {
  const isCategory = isCategorizationParent(metric)
  const children = isCategory ? getEnabledChildren(metric) : []

  return (
    <label
      className={`flex items-start gap-3 cursor-pointer p-3 rounded-xl border transition-all ${
        checked
          ? isCategory
            ? 'bg-purple-50 border-purple-200 shadow-sm'
            : 'bg-primary-50 border-primary-200 shadow-sm'
          : 'border-transparent bg-white hover:border-gray-200 hover:shadow-sm'
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="mt-1 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
      />
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {isCategory && <Layers className="h-3.5 w-3.5 text-purple-600 shrink-0" />}
          <span className="text-sm font-semibold text-gray-900">{metric.name}</span>
        </div>
        {hint ? <p className="mt-0.5 text-xs text-gray-500">{hint}</p> : null}
        {metric.description ? (
          <p className="text-xs text-gray-500 mt-1 line-clamp-2">{metric.description}</p>
        ) : null}
        {isCategory && children.length > 0 ? (
          <p className="mt-1 text-[11px] text-gray-400">{children.length} labels</p>
        ) : null}
      </div>
    </label>
  )
}

export default function SimulationMetricPicker({
  metricRows,
  agentMedium,
  runAgentId,
  selectedScenarioIds,
  scenarioNameById,
  agentNameById,
  selectedMetricIds,
  goldenOptOut,
  onGoldenOptOutChange,
  onChange,
}: Props) {
  const normalizedSelected = normalizeSelectedMetricIds(selectedMetricIds, metricRows)
  const golden = useMemo(
    () => goldenMetrics(metricRows, agentMedium),
    [metricRows, agentMedium],
  )
  const forAgent = useMemo(() => {
    const selected = new Set(selectedScenarioIds)
    return agentMetricsForRun(metricRows, agentMedium, runAgentId).filter((metric) => {
      const links = metric.scenario_ids || []
      if (links.length === 0) return true
      return links.some((id) => selected.has(id))
    })
  }, [metricRows, agentMedium, runAgentId, selectedScenarioIds])
  const forScenarioOnly = useMemo(
    () =>
      scenarioMetricsForRun(metricRows, agentMedium, selectedScenarioIds).filter(
        (metric) => !(metric.agent_ids?.length),
      ),
    [metricRows, agentMedium, selectedScenarioIds],
  )

  const handleToggle = (metric: MetricRow) => {
    const wasChecked = normalizedSelected.includes(metric.id)
    const nextIds = toggleMetricSelection(metric, selectedMetricIds, metricRows)
    if (isGoldenMetric(metric)) {
      const opt = new Set(goldenOptOut)
      if (wasChecked) opt.add(metric.id)
      else opt.delete(metric.id)
      onGoldenOptOutChange(opt)
    }
    onChange(nextIds)
  }

  return (
    <div className="space-y-4">
      <section>
        <h5 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
          Golden metrics
        </h5>
        <p className="mb-2 text-xs text-gray-500">
          Not linked to an agent or scenario — scored on every trial in this run.
        </p>
        <div className="space-y-2 rounded-xl border border-gray-200 bg-gray-50/30 p-3">
          {golden.length === 0 ? (
            <p className="text-sm text-gray-500">No golden metrics enabled for this agent type.</p>
          ) : (
            golden.map((metric) => (
              <MetricCheckboxRow
                key={metric.id}
                metric={metric}
                checked={normalizedSelected.includes(metric.id)}
                hint="All agents and scenarios"
                onToggle={() => handleToggle(metric)}
              />
            ))
          )}
        </div>
      </section>
      <section>
        <h5 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
          Agent-specific metrics
        </h5>
        <p className="mb-2 text-xs text-gray-500">
          Linked to this agent. Scenario links still limit which trials they score.
        </p>
        <div className="space-y-2 rounded-xl border border-gray-200 bg-gray-50/30 p-3">
          {forAgent.length === 0 ? (
            <p className="text-sm text-gray-500">
              No metrics linked to this agent for the selected scenarios.
            </p>
          ) : (
            forAgent.map((metric) => (
              <MetricCheckboxRow
                key={metric.id}
                metric={metric}
                checked={normalizedSelected.includes(metric.id)}
                hint={formatMetricScopeLabel(metric, scenarioNameById, agentNameById)}
                onToggle={() => handleToggle(metric)}
              />
            ))
          )}
        </div>
      </section>
      <section>
        <h5 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
          Scenario-specific metrics
        </h5>
        <p className="mb-2 text-xs text-gray-500">
          Linked to scenarios only — auto-selected when those scenarios are in the run.
        </p>
        <div className="space-y-2 rounded-xl border border-gray-200 bg-gray-50/30 p-3">
          {forScenarioOnly.length === 0 ? (
            <p className="text-sm text-gray-500">No scenario-only metrics for this selection.</p>
          ) : (
            forScenarioOnly.map((metric) => (
              <MetricCheckboxRow
                key={metric.id}
                metric={metric}
                checked={normalizedSelected.includes(metric.id)}
                hint={formatMetricScopeLabel(metric, scenarioNameById, agentNameById)}
                onToggle={() => handleToggle(metric)}
              />
            ))
          )}
        </div>
      </section>
    </div>
  )
}
