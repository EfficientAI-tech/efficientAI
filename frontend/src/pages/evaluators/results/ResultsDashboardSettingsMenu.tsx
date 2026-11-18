import { useEffect, useRef, type ReactNode } from 'react'
import { Plus, RotateCcw, Settings2 } from 'lucide-react'
import type { CallImportMetricAggregate } from '../../../types/api'
import {
  ADDABLE_WIDGETS,
  WIDGET_LABELS,
  type ResultsWidget,
  type ResultsWidgetType,
} from './resultsDashboardLayout'
import { resultsScopeTheme } from './resultsScopeTheme'

type SourceMode = 'simulation' | 'live'

type ResultsDashboardSettingsMenuProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  sampleOn: boolean
  onToggleSample: () => void
  source: SourceMode
  onSourceChange: (source: SourceMode) => void
  metrics: CallImportMetricAggregate[]
  widgets: ResultsWidget[]
  addOpen: boolean
  setAddOpen: (open: boolean | ((value: boolean) => boolean)) => void
  onAddWidget: (type: ResultsWidgetType, metricId?: string) => void
  onResetLayout: () => void
}

export default function ResultsDashboardSettingsMenu({
  open,
  onOpenChange,
  sampleOn,
  onToggleSample,
  source,
  onSourceChange,
  metrics,
  widgets,
  addOpen,
  setAddOpen,
  onAddWidget,
  onResetLayout,
}: ResultsDashboardSettingsMenuProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const theme = resultsScopeTheme

  const settingsActive = open || sampleOn || source === 'live'
  const summaryParts = [
    sampleOn ? 'Sample' : null,
    source === 'simulation' ? 'Simulations' : 'Live',
  ].filter(Boolean)

  useEffect(() => {
    if (!open) return
    const onDoc = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        onOpenChange(false)
        setAddOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open, onOpenChange, setAddOpen])

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className={`inline-flex max-w-full items-center gap-2 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${settingsActive
            ? theme.pillActive
            : 'border-gray-200 bg-white text-gray-600 hover:bg-[#fefce8] hover:text-[#854d0e]'
          }`}
        aria-expanded={open}
      >
        <Settings2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="hidden sm:inline">Dashboard</span>
        <span className="truncate font-normal text-[#854d0e]/80">
          {summaryParts.join(' · ')}
        </span>
      </button>

      {open ? (
        <div
          className={`absolute right-0 top-full z-50 mt-1.5 w-[min(100vw-2rem,20rem)] rounded-xl border border-gray-200 bg-white p-3 shadow-xl ring-1 ring-[#fde047]/40 ${theme.focusRing}`}
          role="dialog"
          aria-label="Dashboard settings"
        >
          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Dashboard</p>

          <MotionRow
            label="Sample data"
            hint="Demo agents and ops when exploring the grid"
          >
            <button
              type="button"
              onClick={onToggleSample}
              className={`rounded-lg border px-2.5 py-1 text-xs font-medium ${sampleOn
                  ? 'border-amber-300 bg-amber-50 text-amber-900'
                  : 'border-gray-200 bg-gray-50 text-gray-600 hover:bg-white'
                }`}
            >
              {sampleOn ? 'On' : 'Off'}
            </button>
          </MotionRow>

          <MotionRow label="Data source" hint="Simulations vs live playground runs">
            <div className="flex items-center rounded-lg bg-gray-100 p-0.5">
              {(['simulation', 'live'] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => onSourceChange(item)}
                  className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${source === item
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-500 hover:text-gray-800'
                    }`}
                >
                  {item === 'simulation' ? 'Simulations' : 'Live'}
                </button>
              ))}
            </div>
          </MotionRow>

          <div className="mt-3 border-t border-gray-100 pt-3">
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => setAddOpen((value) => !value)}
                className={`inline-flex flex-1 items-center justify-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium ${addOpen ? theme.pillActive : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                  }`}
              >
                <Plus className="h-3.5 w-3.5" />
                Add chart
              </button>
              <button
                type="button"
                onClick={() => {
                  onResetLayout()
                  onOpenChange(false)
                }}
                className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reset
              </button>
            </div>

            {addOpen ? (
              <div className="mt-2 max-h-48 overflow-y-auto rounded-lg border border-gray-100 bg-[#fefce8]/40 p-1">
                <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400">Charts</p>
                <div className="space-y-0.5">
                  {ADDABLE_WIDGETS.flatMap((type) => {
                    if (type === 'metric_trend') {
                      if (!metrics.length) {
                        return (
                          <button
                            key={type}
                            type="button"
                            disabled
                            className="block w-full rounded-md px-2 py-1.5 text-left text-xs text-gray-300"
                          >
                            Metric trend
                          </button>
                        )
                      }
                      return [
                        <p
                          key="metric-trend-label"
                          className="px-2 pb-0.5 pt-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400"
                        >
                          Metric trend
                        </p>,
                        ...metrics.map((metric) => {
                          const alreadyVisible = widgets.some(
                            (widget) => widget.type === 'metric_trend' && widget.metricId === metric.metric_id && !widget.hidden,
                          )
                          return (
                            <button
                              key={metric.metric_id}
                              type="button"
                              disabled={alreadyVisible}
                              onClick={() => onAddWidget('metric_trend', metric.metric_id)}
                              className="block w-full rounded-md px-2 py-1.5 text-left text-xs text-gray-700 hover:bg-white disabled:text-gray-300"
                            >
                              {metric.metric_name}
                            </button>
                          )
                        }),
                      ]
                    }
                    const alreadyVisible = widgets.some((widget) => widget.type === type && !widget.hidden)
                    return (
                      <button
                        key={type}
                        type="button"
                        disabled={alreadyVisible}
                        onClick={() => onAddWidget(type)}
                        className="block w-full rounded-md px-2 py-1.5 text-left text-xs text-gray-700 hover:bg-white disabled:text-gray-300"
                      >
                        {WIDGET_LABELS[type]}
                      </button>
                    )
                  })}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function MotionRow({
  label,
  hint,
  children,
  className = '',
}: {
  label: string
  hint?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`mt-2.5 flex items-start justify-between gap-3 ${className}`}>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-gray-800">{label}</p>
        {hint ? <p className="text-[10px] leading-snug text-gray-500">{hint}</p> : null}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}