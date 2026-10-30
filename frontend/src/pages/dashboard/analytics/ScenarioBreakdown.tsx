import { useMemo } from 'react'
import { MOCK_AGENTS, SCENARIOS } from './mockCatalog'
import type { MockCall } from './mockCalls'
import { callFailed } from './callFailed'
import { isGlobalMetricId } from './globalMetrics'

function scenarioScore(calls: MockCall[], metricId: string): { n: number; failing: number; value: number | null } {
  const n = calls.length
  if (n === 0) return { n: 0, failing: 0, value: null }
  const failing = calls.filter((call) => callFailed(call, metricId)).length
  if (isGlobalMetricId(metricId)) {
    return { n, failing, value: failing / n }
  }
  const values = calls
    .map((call) => call.metric_scores[metricId]?.value)
    .map((value) => (typeof value === 'number' ? value : typeof value === 'boolean' ? (value ? 1 : 0) : null))
    .filter((value): value is number => value != null)
  const avg = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : failing / n
  return { n, failing, value: avg }
}

export default function ScenarioBreakdown({
  calls,
  metricId,
  selectedScenarioId,
  onSelectScenario,
}: {
  calls: MockCall[]
  metricId: string | null
  selectedScenarioId: string | null
  onSelectScenario: (scenarioId: string | null) => void
}) {
  const metric = metricId ?? 'mock-metric-empathy'
  const rows = useMemo(() => {
    return SCENARIOS.map((scenario) => {
      const scoped = calls.filter((call) => call.scenarioId === scenario.id)
      return { scenario, ...scenarioScore(scoped, metric) }
    }).sort((a, b) => (b.failing / Math.max(1, b.n)) - (a.failing / Math.max(1, a.n)))
  }, [calls, metric])

  const heatmap = useMemo(() => {
    return SCENARIOS.map((scenario) =>
      MOCK_AGENTS.map((agent) => {
        const scoped = calls.filter((call) => call.scenarioId === scenario.id && call.agentId === agent.id)
        const stats = scenarioScore(scoped, metric)
        return { scenarioId: scenario.id, agentId: agent.id, rate: stats.n ? stats.failing / stats.n : null, n: stats.n }
      }),
    )
  }, [calls, metric])

  const maxBar = Math.max(...rows.map((row) => row.failing / Math.max(1, row.n)), 0.01)

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-900">By scenario</h3>
        {selectedScenarioId && (
          <button type="button" className="text-xs text-gray-500 underline" onClick={() => onSelectScenario(null)}>
            Clear scenario
          </button>
        )}
      </div>
      <div className="mt-3 space-y-2">
        {rows.map((row) => {
          const rate = row.n ? row.failing / row.n : 0
          const active = selectedScenarioId === row.scenario.id
          return (
            <button
              key={row.scenario.id}
              type="button"
              onClick={() => onSelectScenario(active ? null : row.scenario.id)}
              className={`w-full text-left ${active ? 'opacity-100' : 'hover:opacity-90'}`}
            >
              <div className="flex items-center justify-between text-xs text-gray-600">
                <span className={active ? 'font-semibold text-gray-900' : ''}>{row.scenario.name}</span>
                <span className="tabular-nums">
                  {row.n} · {Math.round(rate * 100)}% fail
                </span>
              </div>
              <div className="mt-1 h-2 rounded-full bg-gray-100">
                <div
                  className="h-2 rounded-full bg-rose-400"
                  style={{ width: `${(rate / maxBar) * 100}%` }}
                />
              </div>
            </button>
          )
        })}
      </div>
      <p className="mt-4 text-[11px] font-medium uppercase tracking-wide text-gray-500">Scenario × agent fail rate</p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr>
              <th className="text-left font-medium text-gray-500 pr-2 py-1"> </th>
              {MOCK_AGENTS.map((agent) => (
                <th key={agent.id} className="font-medium text-gray-500 px-1 py-1 text-center">
                  {agent.name.split(' ')[0]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SCENARIOS.map((scenario, rowIndex) => (
              <tr key={scenario.id}>
                <td className="pr-2 py-1 text-gray-600 truncate max-w-[140px]">{scenario.name}</td>
                {heatmap[rowIndex].map((cell) => (
                  <td key={cell.agentId} className="px-1 py-1">
                    <div
                      className="mx-auto h-7 w-10 rounded text-center leading-7 tabular-nums text-white"
                      style={{
                        backgroundColor: cell.rate == null ? '#e5e7eb' : `rgba(244, 63, 94, ${0.2 + cell.rate * 0.8})`,
                        color: cell.rate == null || cell.rate < 0.4 ? '#374151' : '#fff',
                      }}
                      title={`${cell.n} calls`}
                    >
                      {cell.rate == null ? '—' : `${Math.round(cell.rate * 100)}%`}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
