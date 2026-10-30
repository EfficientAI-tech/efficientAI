import { GitBranch, RotateCcw, X } from 'lucide-react'
import { useDashboardLayout } from './dashboardLayout'
import { useDashboardNav } from './dashboardNav'
import { useDashboardFilters } from './useDashboardFilters'
import { RANGE_LABELS, type DashboardRange, type DashboardSource } from './timeBuckets'

const RANGES: DashboardRange[] = ['7d', '30d', '90d']

export default function DashboardFilterBar({
  range,
  source,
  since,
  until,
  onRange,
  onSource,
  onDates,
}: {
  range: DashboardRange
  source: DashboardSource
  since?: string | null
  until?: string | null
  onRange: (range: DashboardRange) => void
  onSource: (source: DashboardSource) => void
  onDates?: (since: string | null, until: string | null) => void
}) {
  const reset = useDashboardLayout((s) => s.reset)
  const nav = useDashboardNav()
  const filters = useDashboardFilters()
  const customRange = Boolean(since && until)
  const today = new Date().toISOString().slice(0, 10)
  const treeOpen = filters.section === 'tree'

  return (
    <div className="sticky top-0 z-20 -mx-1 mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-gray-200 bg-white/95 px-3 py-2.5 shadow-sm backdrop-blur">
      <div className="flex items-center rounded-lg bg-gray-100 p-0.5">
        {RANGES.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => onRange(item)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium ${
              !customRange && range === item ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'
            }`}
          >
            {RANGE_LABELS[item]}
          </button>
        ))}
      </div>

      {onDates && (
        <div className="flex items-center gap-1.5 text-xs text-gray-600">
          <input
            type="date"
            value={since ?? ''}
            max={until ?? today}
            onChange={(event) => {
              const next = event.target.value || null
              onDates(next, until ?? next)
            }}
            className="rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900"
          />
          <span className="text-gray-400">to</span>
          <input
            type="date"
            value={until ?? ''}
            min={since ?? undefined}
            max={today}
            onChange={(event) => {
              const next = event.target.value || null
              onDates(since ?? next, next)
            }}
            className="rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900"
          />
          {customRange && (
            <button type="button" onClick={() => onDates(null, null)} className="text-gray-400 hover:text-gray-700">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      )}

      <div className="flex items-center rounded-lg bg-gray-100 p-0.5">
        <SourceButton
          active={source === 'simulation'}
          color="bg-indigo-500"
          label="Simulations"
          onClick={() => onSource('simulation')}
        />
        <SourceButton
          active={source === 'live'}
          color="bg-teal-500"
          label="Live"
          onClick={() => onSource('live')}
        />
      </div>

      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          onClick={() => (treeOpen ? nav.openOverview() : nav.openTree())}
          className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium ${
            treeOpen
              ? 'border-amber-300 bg-amber-50 text-amber-800'
              : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
          }`}
        >
          <GitBranch className="h-3.5 w-3.5" />
          Metric tree
        </button>
        {filters.section === 'overview' && (
          <button
            type="button"
            onClick={() => reset()}
            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset layout
          </button>
        )}
      </div>
    </div>
  )
}

function SourceButton({
  active,
  color,
  label,
  onClick,
}: {
  active: boolean
  color: string
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium ${
        active ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'
      }`}
    >
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </button>
  )
}
