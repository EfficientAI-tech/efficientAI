import { useMemo, useState } from 'react'
import { callFailed } from './callFailed'
import { aggregateCalls } from './callMetrics'
import DrilldownBreadcrumb from './DrilldownBreadcrumb'
import { formatGlobalValue, globalMetricById } from './globalMetrics'
import { MOCK_AGENTS, MOCK_METRICS } from './mockCatalog'
import type { MockCall } from './mockCalls'
import { RANGE_LABELS, type DashboardRange, type DashboardSource } from './timeBuckets'
import { useDashboardCalls } from './useDashboardCalls'

function evidenceSnippet(call: MockCall, metricId: string): string {
  const score = call.metric_scores[metricId]
  if (score?.rationale) return score.rationale
  const indexes = score?.evidenceTurnIndexes ?? []
  if (indexes.length > 0) return call.turns[indexes[0]]?.text ?? ''
  if (call.endedEarly) return `Ended early (${call.endedReason ?? 'unknown'})`
  const failedTool = call.turns.find((turn) => turn.toolCall?.failed)
  if (failedTool?.toolCall) return `Tool ${failedTool.toolCall.name} failed`
  const failedRag = call.turns.find((turn) => turn.ragCall?.failed)
  if (failedRag?.ragCall) return `RAG failed: ${failedRag.ragCall.query}`
  return call.turns[call.turns.length - 1]?.text ?? ''
}

function displayValue(call: MockCall, metricId: string): string {
  const global = globalMetricById(metricId)
  if (global) {
    const agg = aggregateCalls([call], global.id, global.failRule)
    return formatGlobalValue(global, global.id === 'total_calls' ? 1 : agg.avg)
  }
  const score = call.metric_scores[metricId]
  return score ? String(score.value) : '—'
}

export default function MetricAgentCallsPage({
  metricId,
  agentId,
  range,
  source,
  extra,
  failingOnly = true,
  onBack,
  onBackMetric,
  onOpenCall,
  backLabel = 'Metrics',
}: {
  metricId: string
  agentId: string | null
  range: DashboardRange
  source: DashboardSource
  extra?: { since?: string | null; until?: string | null; scenarioId?: string | null }
  failingOnly?: boolean
  onBack: () => void
  onBackMetric: () => void
  onOpenCall: (callId: string) => void
  backLabel?: string
}) {
  const [showPassing, setShowPassing] = useState(!failingOnly)
  const calls = useDashboardCalls(range, source, agentId, extra)
  const agentName = agentId ? MOCK_AGENTS.find((agent) => agent.id === agentId)?.name ?? 'Agent' : 'All agents'
  const metricName =
    globalMetricById(metricId)?.name ?? MOCK_METRICS.find((metric) => metric.id === metricId)?.name ?? 'Metric'

  const current = calls.current
  const failing = current.filter((call) => callFailed(call, metricId))
  const visible = (showPassing ? current : failing).slice().sort((a, b) => +new Date(b.startedAt) - +new Date(a.startedAt))

  const chips = useMemo(
    () => [
      `${current.length} runs`,
      `${failing.length} failing`,
      current.length ? `${Math.round((failing.length / current.length) * 100)}% fail rate` : 'no rate',
      RANGE_LABELS[range],
    ],
    [current.length, failing.length, range],
  )

  return (
    <div className="space-y-5">
      <DrilldownBreadcrumb
        items={[
          { label: backLabel, onClick: onBack },
          { label: metricName, onClick: onBackMetric },
          { label: agentName },
        ]}
      />
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">
          {agentName}
          <span className="mx-2 text-gray-300">/</span>
          <span className="text-xl font-medium text-gray-700">{metricName}</span>
        </h1>
        <div className="mt-2 flex flex-wrap gap-2">
          {chips.map((chip) => (
            <span key={chip} className="rounded-full bg-gray-100 px-2.5 py-1 text-xs text-gray-700">
              {chip}
            </span>
          ))}
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm text-gray-600">
        <input type="checkbox" checked={showPassing} onChange={(event) => setShowPassing(event.target.checked)} />
        Show passing calls too
      </label>
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-[11px] uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-4 py-2 font-medium">Time</th>
              {!agentId && <th className="px-4 py-2 font-medium">Agent</th>}
              <th className="px-4 py-2 font-medium">Scenario</th>
              <th className="px-4 py-2 font-medium">Duration</th>
              <th className="px-4 py-2 font-medium">Value</th>
              <th className="px-4 py-2 font-medium">Evidence</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={agentId ? 5 : 6} className="px-4 py-8 text-gray-500">
                  {showPassing ? 'No calls in this window.' : 'No failing calls for this metric.'}
                </td>
              </tr>
            ) : (
              visible.map((call) => (
                <tr key={call.id} className="border-t border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => onOpenCall(call.id)}
                      className="font-medium text-gray-900 hover:underline"
                    >
                      {new Date(call.startedAt).toLocaleString()}
                    </button>
                  </td>
                  {!agentId && <td className="px-4 py-3 text-gray-600">{call.agentName}</td>}
                  <td className="px-4 py-3 text-gray-600">{call.scenarioName ?? call.source}</td>
                  <td className="px-4 py-3 tabular-nums text-gray-600">{call.durationSeconds}s</td>
                  <td className="px-4 py-3 tabular-nums font-medium text-gray-900">{displayValue(call, metricId)}</td>
                  <td className="px-4 py-3 text-gray-600 max-w-xs truncate">{evidenceSnippet(call, metricId)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
