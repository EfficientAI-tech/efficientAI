import { useRef } from 'react'
import {
  Area,
  Bar,
  Brush,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { LIVE_COLOR, SIMULATION_COLOR } from '../Sparkline'
import type { ChartType } from '../dashboardLayout'
import type { DashboardSource } from '../timeBuckets'

const TIME_CHART_TYPES: Array<Extract<ChartType, 'line' | 'area' | 'bar'>> = ['line', 'area', 'bar']

export interface TimeChartPoint {
  label: string
  value: number | null
  min?: number | null
  max?: number | null
  live?: number | null
  previous?: number | null
  since?: string
  until?: string
}

export interface ChartAnnotation {
  date: string
  label: string
  kind: 'experiment' | 'break'
}

export default function InteractiveTimeChart({
  points,
  source,
  chartType = 'line',
  unitInterval,
  title,
  onBrush,
  onPointClick,
  onChartTypeChange,
  annotations = [],
}: {
  points: TimeChartPoint[]
  source: DashboardSource
  chartType?: ChartType
  unitInterval?: boolean
  title?: string
  onBrush?: (since: string, until: string) => void
  onPointClick?: (point: TimeChartPoint) => void
  onChartTypeChange?: (chartType: ChartType) => void
  annotations?: ChartAnnotation[]
}) {
  const stroke = source === 'live' ? LIVE_COLOR : SIMULATION_COLOR
  const overlay = source === 'live' ? SIMULATION_COLOR : LIVE_COLOR
  const kind = chartType === 'area' || chartType === 'bar' ? chartType : 'line'
  const brushTimer = useRef<number>()
  const lastBrush = useRef('')

  const handleBrush = (range: { startIndex?: number; endIndex?: number } | undefined) => {
    if (!onBrush || !range || range.startIndex == null || range.endIndex == null) return
    if (range.startIndex === 0 && range.endIndex === points.length - 1) return
    const start = points[range.startIndex]
    const end = points[range.endIndex]
    if (!start?.since || !end?.until) return
    const since = start.since.slice(0, 10)
    const until = end.until.slice(0, 10)
    const key = `${since}|${until}`
    if (key === lastBrush.current) return
    window.clearTimeout(brushTimer.current)
    brushTimer.current = window.setTimeout(() => {
      lastBrush.current = key
      onBrush(since, until)
    }, 400)
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        {title ? <p className="text-sm font-medium text-gray-900">{title}</p> : <span />}
        {onChartTypeChange && (
          <div className="flex items-center rounded-lg bg-gray-100 p-0.5">
            {TIME_CHART_TYPES.map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => onChartTypeChange(type)}
                className={`rounded-md px-2 py-0.5 text-[11px] font-medium capitalize ${
                  kind === type ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'
                }`}
              >
                {type}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={points}
            margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
            onClick={(state) => {
              const label = (state as { activeLabel?: string } | undefined)?.activeLabel
              const point = points.find((item) => item.label === label)
              if (point) onPointClick?.(point)
            }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
            <YAxis
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              axisLine={false}
              tickLine={false}
              width={40}
              domain={unitInterval ? [0, 1] : ['auto', 'auto']}
            />
            <Tooltip />
            <Line type="monotone" dataKey="max" name="Max" stroke="#cbd5e1" strokeWidth={1} dot={false} connectNulls />
            <Line type="monotone" dataKey="min" name="Min" stroke="#cbd5e1" strokeWidth={1} dot={false} connectNulls />
            <Line
              type="monotone"
              dataKey="previous"
              name="Previous"
              stroke="#94a3b8"
              strokeDasharray="4 4"
              strokeWidth={1.5}
              dot={false}
              connectNulls
            />
            {kind === 'bar' && <Bar dataKey="value" name="Current" fill={stroke} radius={[4, 4, 0, 0]} />}
            {kind === 'area' && (
              <Area
                type="monotone"
                dataKey="value"
                name="Current"
                stroke={stroke}
                fill={stroke}
                fillOpacity={0.15}
                strokeWidth={2}
                connectNulls
              />
            )}
            {kind === 'line' && (
              <Line type="monotone" dataKey="value" name="Current" stroke={stroke} strokeWidth={2} dot={{ r: 3 }} connectNulls />
            )}
            <Line
              type="monotone"
              dataKey="live"
              name={source === 'live' ? 'Simulations' : 'Live'}
              stroke={overlay}
              strokeWidth={1.5}
              strokeOpacity={0.7}
              dot={false}
              connectNulls
            />
            {annotations.map((annotation) => {
              const point = points.find((item) => item.since === annotation.date || item.label === annotation.date)
              if (!point) return null
              return (
                <ReferenceLine
                  key={`${annotation.kind}-${annotation.date}`}
                  x={point.label}
                  stroke={annotation.kind === 'experiment' ? '#8b5cf6' : '#f59e0b'}
                  strokeDasharray="3 3"
                  label={{ value: annotation.label, position: 'top', fontSize: 10, fill: '#6b7280' }}
                />
              )
            })}
            <Brush
              dataKey="label"
              height={18}
              stroke="#94a3b8"
              travellerWidth={8}
              onChange={(range) => handleBrush(range as { startIndex?: number; endIndex?: number })}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-[11px] text-gray-400">Drag the brush to set dates. Click a point for that day’s calls.</p>
    </div>
  )
}
