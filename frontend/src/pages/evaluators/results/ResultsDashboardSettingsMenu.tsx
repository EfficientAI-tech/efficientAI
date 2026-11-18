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
          className={`absolute right-0 top-full z-50 mt-1.5 w-[min(100vw-2rem,22rem)] rounded-xl border border-gray-200 bg-white p-3 shadow-xl ring-1 ring-[#fde047]/40 ${theme.focusRing}`}
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
              <div className="mt-2.5 rounded-xl border border-[#fde047]/50 bg-gradient-to-b from-[#fefce8]/80 to-white p-2 shadow-inner">
                <p className="px-1 pb-1.5 text-[10px] leading-snug text-gray-500">
                  Pick a chart to drop on the grid. Options already on the dashboard are dimmed.
                </p>
                <div className="max-h-52 space-y-1 overflow-y-auto pr-0.5">
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
                          <p className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wide text-[#854d0e]/70">
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
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`group flex w-full items-center gap-2 rounded-md border px-1.5 py-1.5 text-left transition-all ${disabled
        ? 'cursor-not-allowed border-transparent bg-gray-50/80'
        : 'border-gray-200/80 bg-white hover:border-primary-300 hover:bg-primary-50/40'
        }`}
    >
      <span
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${disabled ? 'bg-gray-100 text-gray-400' : 'bg-primary-100 text-primary-900'
          }`}
      >
        <Icon className="h-3 w-3" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-1">
          <span className={`text-xs font-medium leading-tight ${disabled ? 'text-gray-400' : 'text-gray-900'}`}>
            {label}
          </span>
          {added ? (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-gray-200/80 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-gray-600">
              <Check className="h-2 w-2" aria-hidden />
              On board
            </span>
          ) : (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-primary-100 px-1 py-px text-[9px] font-semibold text-primary-900 opacity-0 transition-opacity group-hover:opacity-100">
              <Plus className="h-2 w-2" aria-hidden />
              Add
            </span>
          )}
        </span>
        <span className={`mt-px block text-[10px] leading-snug ${disabled ? 'text-gray-400' : 'text-gray-500'}`}>
          {blurb}
        </span>
      </span>
    </button>
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