import { useState } from 'react'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical, MoreHorizontal } from 'lucide-react'
import {
  CHART_TYPE_LABELS,
  WIDGET_META,
  type ChartType,
  type WidgetDisplay,
  type WidgetInstance,
  useDashboardLayout,
} from './dashboardLayout'
import { WIDGET_COLORS, withAlpha } from './dashboardSection'
import { RANGE_LABELS } from './timeBuckets'
import { useDashboardFilters } from './useDashboardFilters'
import { useDashboardNav } from './dashboardNav'
import { MOCK_AGENTS } from './mockCatalog'
import WidgetBody from './WidgetBody'

const DISPLAYS: WidgetDisplay[] = ['number', 'line', 'area', 'bar', 'stacked', 'donut']

export default function WidgetCard({
  widget,
  compact,
}: {
  widget: WidgetInstance
  compact?: 'top' | 'rail'
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: widget.id })
  const setDisplay = useDashboardLayout((s) => s.setDisplay)
  const setAgent = useDashboardLayout((s) => s.setAgent)
  const setHidden = useDashboardLayout((s) => s.setHidden)
  const removeWidget = useDashboardLayout((s) => s.removeWidget)
  const filters = useDashboardFilters()
  const nav = useDashboardNav()
  const [menu, setMenu] = useState(false)
  const [details, setDetails] = useState(false)
  const meta = WIDGET_META[widget.type]
  const period =
    filters.since && filters.until
      ? `${filters.since} – ${filters.until}`
      : `Last ${RANGE_LABELS[filters.range]}`
  const accent = compact === 'top' ? undefined : WIDGET_COLORS[widget.type]
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.55 : widget.hidden ? 0.4 : 1,
    ...(accent ? { borderTopColor: accent, borderTopWidth: 3 } : {}),
  }
  const showAgentFilter = compact === 'top' && widget.type !== 'scenarios'

  const onShowDetails = () => {
    if (widget.type === 'cost') {
      nav.openUsage()
      return
    }
    if (widget.type === 'tool_calls') {
      nav.openToolCalls()
      return
    }
    if (widget.type === 'tool_use') {
      nav.openTools()
      return
    }
    if (widget.type === 'failures') {
      nav.openFailures()
      return
    }
    if (widget.type === 'closing_quality' || widget.type === 'early_ending' || widget.type === 'talk_ratio') {
      nav.openMetric(widget.type)
      return
    }
    if (widget.type === 'rag_failures') {
      nav.openMetric('rag_call_failures')
      return
    }
    if (widget.type === 'silence_duration' || widget.type === 'longest_pause') {
      nav.openMetric(widget.type)
      return
    }
    setDetails((value) => !value)
  }

  return (
    <article
      ref={setNodeRef}
      style={{
        ...style,
        ...(accent
          ? {
              borderColor: withAlpha(accent, 0.28),
              background: `linear-gradient(180deg, ${withAlpha(accent, 0.16)} 0%, ${withAlpha(accent, 0.04)} 46%, #ffffff 100%)`,
            }
          : {}),
      }}
      className={`group relative overflow-hidden flex h-full flex-col rounded-xl border bg-white ${
        compact === 'rail' ? 'p-3' : compact === 'top' ? 'min-h-[156px] border-gray-200 p-4' : 'min-h-[280px] p-5 shadow-sm'
      } ${isDragging ? 'shadow-md' : ''}`}
    >
      {accent && (
        <div
          className="pointer-events-none absolute -right-8 -top-10 h-32 w-32 rounded-full blur-2xl"
          style={{ backgroundColor: withAlpha(accent, 0.28) }}
        />
      )}
      <div className="relative mb-3 flex items-start gap-2">
        <button
          type="button"
          className="mt-0.5 cursor-grab rounded p-0.5 text-gray-300 opacity-0 hover:text-gray-600 group-hover:opacity-100 active:cursor-grabbing"
          aria-label="Drag widget"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-3.5 w-3.5" />
        </button>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-gray-400">
            {meta.category} · {period}
          </p>
          <h3 className="mt-1 truncate text-[15px] font-semibold text-gray-900">{meta.label}</h3>
        </div>
        {showAgentFilter && (
          <select
            aria-label="Filter by agent"
            value={widget.agentId ?? ''}
            onChange={(event) => setAgent(widget.id, event.target.value || null)}
            className="max-w-[132px] truncate rounded-md border border-gray-200 bg-white px-1.5 py-1 text-[11px] text-gray-600"
          >
            <option value="">All agents</option>
            {MOCK_AGENTS.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
        )}
        {widget.type === 'cost' && compact !== 'rail' && (
          <div className="inline-flex rounded-md bg-gray-100 p-0.5">
            {(['USD', 'INR'] as const).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => nav.setCurrency(item)}
                className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                  nav.currency === item ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'
                }`}
              >
                {item}
              </button>
            ))}
          </div>
        )}
        {compact !== 'rail' && (
          <button
            type="button"
            onClick={onShowDetails}
            className="hidden items-center gap-1 rounded-md px-1.5 py-1 text-xs text-gray-500 hover:bg-gray-50 hover:text-gray-800 sm:inline-flex"
          >
            {details ? 'Hide details' : 'Show details'}
          </button>
        )}
        <div className="relative">
          <button
            type="button"
            onClick={() => setMenu((value) => !value)}
            className="rounded p-1 text-gray-400 hover:bg-gray-50 hover:text-gray-700"
            aria-label="Widget options"
          >
            <MoreHorizontal className="h-4 w-4" />
          </button>
          {menu && (
            <div className="absolute right-0 z-20 mt-1 w-36 rounded-lg border border-gray-200 bg-white py-1 text-xs shadow-lg">
              {DISPLAYS.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => {
                    setDisplay(widget.id, item)
                    setMenu(false)
                  }}
                  className={`block w-full px-2.5 py-1 text-left hover:bg-gray-50 ${
                    widget.display === item ? 'font-medium text-gray-900' : 'text-gray-600'
                  }`}
                >
                  {item === 'number' ? 'Number' : CHART_TYPE_LABELS[item as ChartType]}
                </button>
              ))}
              <button
                type="button"
                onClick={() => {
                  setHidden(widget.id, !widget.hidden)
                  setMenu(false)
                }}
                className="block w-full px-2.5 py-1 text-left text-gray-600 hover:bg-gray-50"
              >
                {widget.hidden ? 'Show' : 'Hide'}
              </button>
              <button
                type="button"
                onClick={() => {
                  removeWidget(widget.id)
                  setMenu(false)
                }}
                className="block w-full px-2.5 py-1 text-left text-rose-700 hover:bg-rose-50"
              >
                Remove
              </button>
            </div>
          )}
        </div>
      </div>
      {!widget.hidden && (
        <div className="relative min-h-0 flex-1">
          <WidgetBody
            type={widget.type}
            display={widget.display}
            compact={compact}
            details={details}
            agentId={widget.agentId}
          />
        </div>
      )}
    </article>
  )
}
