import { useEffect, useRef, type ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  BarChart3,
  Check,
  Clock,
  Coins,
  Grid3x3,
  LineChart,
  PieChart,
  Plus,
  RotateCcw,
  Settings2,
  TrendingDown,
  Wrench,
} from 'lucide-react'
import type { CallImportMetricAggregate } from '../../../types/api'
import {
  ADDABLE_WIDGETS,
  WIDGET_LABELS,
  type ResultsWidget,
  type ResultsWidgetType,
} from './resultsDashboardLayout'
import { resultsScopeTheme } from './resultsScopeTheme'

type SourceMode = 'simulation' | 'live'

const WIDGET_PICKER_META: Partial<
  Record<ResultsWidgetType, { icon: LucideIcon; blurb: string }>
> = {
  total_calls: { icon: BarChart3, blurb: 'Run counts per agent' },
  tools: { icon: Wrench, blurb: 'Products, share, and use cases' },
  usage: { icon: Coins, blurb: 'Pre-prod LLM spend in window' },
  completion: { icon: PieChart, blurb: 'Completed vs failed over time' },
  avg_duration: { icon: Clock, blurb: 'Mean call length by day' },
  metric_usage: { icon: LineChart, blurb: 'Which agents scored metrics' },
  lowest_metrics: { icon: TrendingDown, blurb: 'Bottom mean scores' },
  scenarios_by_agent: { icon: Grid3x3, blurb: 'Stacked scenarios per agent' },
  metric_trend: { icon: LineChart, blurb: 'Daily average for one metric' },
}

type ResultsDashboardSettingsMenuProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
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

  const settingsActive = open || source === 'live'
  const summaryParts = [source === 'simulation' ? 'Simulations' : 'Live']

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

  const isWidgetVisible = (type: ResultsWidgetType, metricId?: string) =>
    widgets.some(
      (widget) =>
        widget.type === type
        && !widget.hidden
        && (metricId == null || widget.metricId === metricId),
    )

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className={`inline-flex max-w-full items-center gap-2 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${settingsActive
          ? theme.pillActive
          : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50 hover:text-gray-900'
          }`}
        aria-expanded={open}
      >
        <Settings2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="hidden sm:inline">Dashboard</span>
        <span className="truncate font-normal text-gray-500">
          {summaryParts.join(' · ')}
        </span>
      </button>

      {open ? (
        <div
          className={`absolute right-0 top-full z-50 mt-1.5 w-[min(100vw-2rem,20rem)] rounded-lg border border-gray-200 bg-white p-3 shadow-lg ${theme.focusRing}`}
          role="dialog"
          aria-label="Dashboard settings"
        >
          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Dashboard</p>

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
                aria-expanded={addOpen}
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
              <div className="mt-2.5 border-t border-gray-100 pt-2.5">
                <p className="mb-2 px-0.5 text-[11px] text-gray-500">
                  Hover a row for what it adds. Grayed items are already on the grid.
                </p>
                <div className="max-h-56 space-y-0.5 overflow-y-auto scroll-pt-2 pt-8">
                  {ADDABLE_WIDGETS.flatMap((type) => {
                    if (type === 'metric_trend') {
                      if (!metrics.length) {
                        return [
                          <ChartPickerRow
                            key="metric_trend_empty"
                            label="Metric trend"
                            blurb="Add metrics to your workspace first"
                            icon={LineChart}
                            disabled
                          />,
                        ]
                      }
                      return [
                        <div key="metric-trend-heading" className="pt-1">
                          <p className="px-1 pb-1 text-[10px] font-medium uppercase tracking-wide text-gray-400">
                            Metric trend
                          </p>
                          <div className="space-y-1">
                            {metrics.map((metric) => {
                              const added = isWidgetVisible('metric_trend', metric.metric_id)
                              return (
                                <ChartPickerRow
                                  key={metric.metric_id}
                                  label={metric.metric_name}
                                  blurb="Daily score trend"
                                  icon={LineChart}
                                  disabled={added}
                                  added={added}
                                  onClick={() => onAddWidget('metric_trend', metric.metric_id)}
                                />
                              )
                            })}
                          </div>
                        </div>,
                      ]
                    }
                    const added = isWidgetVisible(type)
                    const meta = WIDGET_PICKER_META[type]
                    return (
                      <ChartPickerRow
                        key={type}
                        label={WIDGET_LABELS[type]}
                        blurb={meta?.blurb ?? 'Dashboard chart'}
                        icon={meta?.icon ?? BarChart3}
                        disabled={added}
                        added={added}
                        onClick={() => onAddWidget(type)}
                      />
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

function ChartPickerRow({
  label,
  blurb,
  icon: Icon,
  disabled,
  added,
  onClick,
}: {
  label: string
  blurb: string
  icon: LucideIcon
  disabled?: boolean
  added?: boolean
  onClick?: () => void
}) {
  return (
    <div className="group relative">
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        aria-label={disabled ? `${label} (already on dashboard)` : `Add ${label}`}
        className={`flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left transition-colors ${disabled
          ? 'cursor-default text-gray-400'
          : 'text-gray-800 hover:bg-gray-50'
          }`}
      >
        <Icon className="h-3.5 w-3.5 shrink-0 text-gray-500" aria-hidden />
        <span className={`min-w-0 flex-1 truncate text-xs font-medium ${disabled ? 'text-gray-400' : ''}`}>
          {label}
        </span>
        {added ? (
          <Check className="h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden />
        ) : (
          <Plus className="h-3.5 w-3.5 shrink-0 text-gray-400 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
        )}
      </button>
      {!disabled ? (
        <p
          role="tooltip"
          className="pointer-events-none absolute bottom-full left-0 right-0 z-20 mb-1 hidden rounded border border-gray-200 bg-white px-2 py-1 text-[11px] leading-snug text-gray-600 shadow-md group-hover:block"
        >
          {blurb}
        </p>
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