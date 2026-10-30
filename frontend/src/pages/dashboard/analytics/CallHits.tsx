import { formatDuration } from './globalMetrics'
import type { MockCall } from './mockCalls'
import { formatMoney, type Currency } from './mockUsage'

export default function CallHits({
  calls,
  currency,
  onOpenCall,
  extra,
}: {
  calls: MockCall[]
  currency: Currency
  onOpenCall: (callId: string) => void
  extra?: (call: MockCall) => string
}) {
  if (calls.length === 0) {
    return <p className="text-sm text-gray-500">No calls in this view.</p>
  }
  return (
    <ul className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white">
      {calls.map((call) => (
        <li key={call.id}>
          <button
            type="button"
            onClick={() => onOpenCall(call.id)}
            className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-gray-50"
          >
            <span className="w-36 shrink-0 text-xs text-gray-500">
              {new Date(call.startedAt).toLocaleString()}
            </span>
            <span className="w-28 shrink-0 truncate text-gray-700">{call.agentName}</span>
            <span className="min-w-0 flex-1 truncate text-gray-600">{call.scenarioName ?? '—'}</span>
            <span className="w-16 tabular-nums text-gray-500">{formatDuration(call.durationSeconds)}</span>
            <span className="w-20 tabular-nums text-gray-500">{formatMoney(call.usage.costUsd, currency)}</span>
            {extra && <span className="w-28 truncate text-right text-xs text-gray-500">{extra(call)}</span>}
          </button>
        </li>
      ))}
    </ul>
  )
}
