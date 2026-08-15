import { X } from 'lucide-react'
import { formatUsageCostUsd } from '../../lib/usageCurrency'

type UsageCosts = {
  input_cost_usd: number
  output_cost_usd: number
  cache_read_cost_usd: number
  cache_write_cost_usd: number
  reasoning_cost_usd: number
  audio_cost_usd: number
  tts_cost_usd: number
  total_cost_usd: number
  has_unpriced_usage?: boolean
}

type Props = {
  isOpen: boolean
  onClose: () => void
  costs?: UsageCosts | null
  scopeLabel?: string
  formatCost?: (usd?: number | null) => string
}

function defaultFormatCostUsd(usd?: number | null): string {
  const formatted = formatUsageCostUsd(usd, 'USD', 1)
  return formatted === '—' ? '$0.00' : formatted
}

const LINE_ITEMS: Array<{ key: keyof UsageCosts; label: string }> = [
  { key: 'input_cost_usd', label: 'Input tokens' },
  { key: 'output_cost_usd', label: 'Output tokens' },
  { key: 'cache_read_cost_usd', label: 'Cache read' },
  { key: 'cache_write_cost_usd', label: 'Cache write' },
  { key: 'reasoning_cost_usd', label: 'Reasoning' },
  { key: 'audio_cost_usd', label: 'Audio / STT' },
  { key: 'tts_cost_usd', label: 'TTS' },
]

export default function UsageCostBreakdownModal({
  isOpen,
  onClose,
  costs,
  scopeLabel,
  formatCost = defaultFormatCostUsd,
}: Props) {
  if (!isOpen) return null

  const rows = LINE_ITEMS.filter((item) => Number(costs?.[item.key] || 0) > 0)

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        <div
          className="fixed inset-0 bg-gray-500/60 transition-opacity"
          onClick={onClose}
          aria-hidden
        />
        <div
          className="relative w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
          role="dialog"
          aria-modal="true"
          aria-labelledby="usage-cost-breakdown-title"
        >
          <div className="mb-5 flex items-start justify-between gap-3">
            <div>
              <h2 id="usage-cost-breakdown-title" className="text-lg font-semibold text-gray-900">
                Cost breakdown
              </h2>
              {scopeLabel ? (
                <p className="mt-1 text-sm text-gray-500">{scopeLabel}</p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {costs?.has_unpriced_usage ? (
            <p className="mb-4 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              Some usage in this range has no pricing rate — estimated cost may be understated.
            </p>
          ) : null}

          <div className="rounded-xl border border-gray-200 overflow-hidden">
            <div className="flex items-center justify-between bg-gray-50 px-4 py-3 border-b border-gray-200">
              <span className="text-sm font-medium text-gray-700">Estimated total</span>
              <span className="text-base font-semibold text-gray-900 tabular-nums">
                {formatCost(costs?.total_cost_usd)}
              </span>
            </div>
            {rows.length > 0 ? (
              <ul className="divide-y divide-gray-100">
                {rows.map((item) => (
                  <li
                    key={item.key}
                    className="flex items-center justify-between px-4 py-2.5 text-sm"
                  >
                    <span className="text-gray-600">{item.label}</span>
                    <span className="font-medium text-gray-900 tabular-nums">
                      {formatCost(costs?.[item.key] as number)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-4 py-6 text-center text-sm text-gray-500">
                No per-metric cost detail for this range.
              </p>
            )}
          </div>

          <div className="mt-5 flex justify-end">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
