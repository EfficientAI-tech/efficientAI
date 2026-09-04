import { useMemo, useState } from 'react'
import { BarChart3, TrendingUp } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export type TrendChartType = 'line' | 'bar'

export interface TrendSeries {
  key: string
  label: string
  color: string
  total: number
}

interface ResultsMetricTrendCardProps {
  title: string
  subtitle?: string
  series: TrendSeries[]
  data: Array<Record<string, string | number>>
  defaultChartType?: TrendChartType
  yAxisAllowDecimals?: boolean
  emptyMessage?: string
}

function ChartTypeToggle({
  value,
  onChange,
}: {
  value: TrendChartType
  onChange: (type: TrendChartType) => void
}) {
  const options: { type: TrendChartType; label: string; icon: typeof BarChart3 }[] = [
    { type: 'bar', label: 'Bar', icon: BarChart3 },
    { type: 'line', label: 'Line', icon: TrendingUp },
  ]
  return (
    <div className="inline-flex items-center rounded-lg border border-gray-200 bg-gray-50/80 p-0.5">
      {options.map(({ type, label, icon: Icon }) => (
        <button
          key={type}
          type="button"
          title={label}
          aria-pressed={value === type}
          onClick={() => onChange(type)}
          className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-all ${
            value === type
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-500 hover:bg-white/70 hover:text-gray-800'
          }`}
        >
          <Icon className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">{label}</span>
        </button>
      ))}
    </div>
  )
}

function TrendTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ name?: string; value?: number; color?: string }>
  label?: string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-gray-200 bg-white/95 px-3 py-2 shadow-lg text-xs">
      <p className="font-medium text-gray-500 mb-1.5">{label}</p>
      {payload.map((entry) => (
        <div key={entry.name} className="flex items-center justify-between gap-4 py-0.5">
          <span className="flex items-center gap-1.5 text-gray-700">
            <span
              className="h-2 w-2 rounded-full shrink-0"
              style={{ backgroundColor: entry.color }}
            />
            {entry.name}
          </span>
          <span className="font-semibold text-gray-900 tabular-nums">
            {typeof entry.value === 'number' ? entry.value.toLocaleString() : entry.value}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function ResultsMetricTrendCard({
  title,
  subtitle,
  series,
  data,
  defaultChartType = 'line',
  yAxisAllowDecimals = true,
  emptyMessage = 'No data available for this period',
}: ResultsMetricTrendCardProps) {
  const [chartType, setChartType] = useState<TrendChartType>(defaultChartType)
  const hasData = data.length > 0 && series.some((s) => s.total > 0)

  const totalLabel = useMemo(() => {
    if (series.length === 1) {
      return `Total: ${series[0].total.toLocaleString()}`
    }
    return series.map((s) => `${s.label}: ${s.total.toLocaleString()}`).join(' · ')
  }, [series])

  return (
    <article className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden flex flex-col min-h-[280px]">
      <header className="px-4 pt-4 pb-3 border-b border-gray-100 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-gray-900 truncate">{title}</h3>
            {subtitle ? (
              <p className="text-[11px] text-gray-500 mt-0.5">{subtitle}</p>
            ) : (
              <p className="text-[11px] text-gray-500 mt-0.5 truncate" title={totalLabel}>
                {totalLabel}
              </p>
            )}
          </div>
          <ChartTypeToggle value={chartType} onChange={setChartType} />
        </div>
        {series.length > 0 ? (
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {series.map((s) => (
              <span
                key={s.key}
                className="inline-flex items-center gap-1.5 text-[11px] text-gray-600 tabular-nums"
              >
                <span
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{ backgroundColor: s.color }}
                />
                <span className="truncate max-w-[120px]" title={s.label}>
                  {s.label}
                </span>
                <span className="text-gray-400">·</span>
                <span className="font-medium text-gray-800">{s.total.toLocaleString()}</span>
              </span>
            ))}
          </div>
        ) : null}
      </header>

      <div className="flex-1 px-2 pb-3 pt-2 min-h-[200px]">
        {!hasData ? (
          <div className="h-[200px] flex items-center justify-center text-xs text-gray-400">
            {emptyMessage}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            {chartType === 'bar' ? (
              <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis
                  dataKey="day"
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  axisLine={{ stroke: '#e2e8f0' }}
                  tickLine={false}
                />
                <YAxis
                  allowDecimals={yAxisAllowDecimals}
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  axisLine={false}
                  tickLine={false}
                  width={36}
                />
                <Tooltip content={<TrendTooltip />} />
                {series.map((s) => (
                  <Bar
                    key={s.key}
                    dataKey={s.key}
                    name={s.label}
                    fill={s.color}
                    radius={[3, 3, 0, 0]}
                    maxBarSize={series.length > 1 ? 18 : 32}
                  />
                ))}
              </BarChart>
            ) : (
              <LineChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis
                  dataKey="day"
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  axisLine={{ stroke: '#e2e8f0' }}
                  tickLine={false}
                />
                <YAxis
                  allowDecimals={yAxisAllowDecimals}
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  axisLine={false}
                  tickLine={false}
                  width={36}
                />
                <Tooltip content={<TrendTooltip />} />
                {series.map((s) => (
                  <Line
                    key={s.key}
                    type="monotone"
                    dataKey={s.key}
                    name={s.label}
                    stroke={s.color}
                    strokeWidth={2}
                    dot={{ r: 2.5, strokeWidth: 0, fill: s.color }}
                    activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }}
                    connectNulls
                  />
                ))}
              </LineChart>
            )}
          </ResponsiveContainer>
        )}
      </div>
    </article>
  )
}
