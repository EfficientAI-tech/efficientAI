import type { TimeChartPoint } from './charts/InteractiveTimeChart'
import type { MockCall } from './mockCalls'
import { callFailed } from './callFailed'

export default function PointDetailPopover({
  point,
  calls,
  metricId,
  onViewCalls,
  onClose,
}: {
  point: TimeChartPoint
  calls: MockCall[]
  metricId: string | null
  onViewCalls: () => void
  onClose: () => void
}) {
  const failing = metricId ? calls.filter((call) => callFailed(call, metricId)).length : 0
  const topScenario = (() => {
    const counts = new Map<string, number>()
    for (const call of calls) {
      if (!call.scenarioName) continue
      counts.set(call.scenarioName, (counts.get(call.scenarioName) ?? 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
  })()

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-gray-500">Selected window</p>
          <h3 className="text-sm font-semibold text-gray-900">{point.label}</h3>
        </div>
        <button type="button" onClick={onClose} className="text-xs text-gray-500 hover:text-gray-800">
          Close
        </button>
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
        <div>
          <dt className="text-[11px] text-gray-500">Calls</dt>
          <dd className="font-semibold tabular-nums text-gray-900">{calls.length}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-gray-500">Value</dt>
          <dd className="font-semibold tabular-nums text-gray-900">
            {point.value == null ? '—' : Number(point.value.toFixed(2))}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-gray-500">Failing</dt>
          <dd className="font-semibold tabular-nums text-gray-900">{failing}</dd>
        </div>
      </dl>
      {topScenario && <p className="mt-2 text-xs text-gray-600">Most common scenario: {topScenario}</p>}
      <button
        type="button"
        onClick={onViewCalls}
        className="mt-3 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
      >
        View calls in this bucket
      </button>
    </div>
  )
}
