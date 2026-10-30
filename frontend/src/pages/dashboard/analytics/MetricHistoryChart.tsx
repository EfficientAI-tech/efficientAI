import { useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { LIVE_COLOR, SIMULATION_COLOR } from './Sparkline'
import type { DashboardSource } from './timeBuckets'

export default function MetricHistoryChart({
  points,
  previousValue,
  source,
  unitInterval,
  compactLabel,
}: {
  points: Array<{ label: string; value: number | null; min?: number | null; max?: number | null }>
  previousValue?: number | null
  source: DashboardSource
  unitInterval?: boolean
  compactLabel?: string
}) {
  const [expanded, setExpanded] = useState(false)
  const chartData = points.map((point) => ({
    label: point.label,
    value: point.value,
    min: point.min ?? null,
    max: point.max ?? null,
    previous: previousValue ?? null,
  }))
  const stroke = source === 'live' ? LIVE_COLOR : SIMULATION_COLOR
  const height = expanded ? 280 : 140

  return (
    <button
      type="button"
      onClick={() => setExpanded((value) => !value)}
      className="w-full rounded-xl border border-gray-200 bg-white p-4 text-left hover:border-gray-300"
    >
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-medium text-gray-900">
          {compactLabel ?? 'History'}
          <span className="ml-2 text-xs font-normal text-gray-500">
            {expanded ? 'Click to collapse' : 'Click to expand'}
          </span>
        </p>
      </div>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
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
            {expanded && (
              <Line type="monotone" dataKey="max" name="Max" stroke="#cbd5e1" strokeWidth={1} dot={false} connectNulls />
            )}
            {expanded && (
              <Line type="monotone" dataKey="min" name="Min" stroke="#cbd5e1" strokeWidth={1} dot={false} connectNulls />
            )}
            {previousValue != null && (
              <Line
                type="monotone"
                dataKey="previous"
                name="Previous period"
                stroke="#94a3b8"
                strokeDasharray="4 4"
                strokeWidth={1.5}
                dot={false}
              />
            )}
            <Line type="monotone" dataKey="value" name="Current" stroke={stroke} strokeWidth={2} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </button>
  )
}
