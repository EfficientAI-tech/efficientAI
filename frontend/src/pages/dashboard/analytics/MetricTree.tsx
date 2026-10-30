import { useMemo, useState } from 'react'
import { METRIC_DEPENDENCIES } from './mockCatalog'
import type { MockCall } from './mockCalls'
import { metricTreeValues } from './dashboardSelectors'

export default function MetricTree({
  calls,
  onSelect,
}: {
  calls: MockCall[]
  onSelect: (metricId: string) => void
}) {
  const values = useMemo(() => metricTreeValues(calls), [calls])
  const [hover, setHover] = useState<string | null>(null)

  const related = useMemo(() => {
    if (!hover) return new Set<string>()
    const set = new Set<string>([hover])
    const node = METRIC_DEPENDENCIES.find((item) => item.id === hover)
    for (const id of node?.drives ?? []) set.add(id)
    for (const item of METRIC_DEPENDENCIES) {
      if (item.drives.includes(hover)) set.add(item.id)
    }
    return set
  }, [hover])

  return (
    <aside className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="mb-4">
        <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-gray-400">Dependencies · L1 → L2 → L3</p>
        <h3 className="mt-1 text-[15px] font-semibold text-gray-900">Metric tree</h3>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {([1, 2, 3] as const).map((level) => (
          <div key={level}>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
              L{level} {level === 1 ? 'outcomes' : level === 2 ? 'drivers' : 'signals'}
            </p>
            <div className="space-y-1.5">
              {METRIC_DEPENDENCIES.filter((node) => node.level === level).map((node) => {
                const active = hover ? related.has(node.id) : true
                const value = values[node.id]
                return (
                  <button
                    key={node.id}
                    type="button"
                    onMouseEnter={() => setHover(node.id)}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => onSelect(node.id)}
                    className={`flex w-full items-center justify-between gap-2 rounded-lg border px-2.5 py-2 text-left text-xs transition ${
                      hover === node.id
                        ? 'border-gray-900 bg-gray-900 text-white'
                        : active
                          ? 'border-gray-200 bg-white text-gray-800 hover:border-gray-300'
                          : 'border-gray-100 bg-gray-50 text-gray-400'
                    }`}
                  >
                    <span className="truncate font-medium">{node.name}</span>
                    <span className={`tabular-nums ${hover === node.id ? 'text-white/80' : 'text-gray-500'}`}>
                      {value?.display ?? '—'}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}
