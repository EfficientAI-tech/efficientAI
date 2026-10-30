import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { CHART_PALETTE } from '../dashboardSection'

function withAlpha(hex: string, alpha: number) {
  const raw = hex.replace('#', '')
  const full = raw.length === 3 ? raw.split('').map((char) => `${char}${char}`).join('') : raw
  const value = Number.parseInt(full, 16)
  if (Number.isNaN(value)) return hex
  const r = (value >> 16) & 255
  const g = (value >> 8) & 255
  const b = value & 255
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

export default function InsightTrendChart({
  points,
  kind = 'bar',
  series,
  height = 220,
  color,
  quiet = false,
}: {
  points: Array<Record<string, string | number>>
  kind?: 'bar' | 'area' | 'line' | 'stacked'
  series?: Array<{ key: string; label: string; color?: string }>
  height?: number
  color?: string
  quiet?: boolean
}) {
  const fallback = color ?? CHART_PALETTE[0]
  const keys = series?.length ? series : [{ key: 'value', label: 'Value', color: fallback }]
  const isQuiet = quiet || height <= 80
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: isQuiet ? 4 : 8, right: 8, left: 0, bottom: isQuiet ? 0 : 4 }}>
          {!isQuiet && <CartesianGrid vertical={false} stroke="#f3f4f6" />}
          <XAxis
            dataKey="label"
            hide={isQuiet}
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            hide={isQuiet}
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            tickLine={false}
            axisLine={false}
            width={40}
          />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: '#e5e7eb' }}
            formatter={(value, name) => [typeof value === 'number' ? Number(value.toFixed(2)) : value, name]}
          />
          {keys.map((item, index) => {
            const stroke = item.color ?? (index === 0 ? fallback : CHART_PALETTE[index % CHART_PALETTE.length])
            if (kind === 'area') {
              return (
                <Area
                  key={item.key}
                  type="monotone"
                  dataKey={item.key}
                  name={item.label}
                  stroke={stroke}
                  fill={withAlpha(stroke, isQuiet ? 0.08 : 0.32)}
                  fillOpacity={1}
                  strokeWidth={isQuiet ? 1.5 : 2.25}
                  dot={false}
                />
              )
            }
            if (kind === 'line') {
              return (
                <Line
                  key={item.key}
                  type="monotone"
                  dataKey={item.key}
                  name={item.label}
                  stroke={stroke}
                  strokeWidth={isQuiet ? 1.5 : 2.25}
                  dot={false}
                />
              )
            }
            return (
              <Bar
                key={item.key}
                dataKey={item.key}
                name={item.label}
                stackId={kind === 'stacked' ? 'a' : item.key}
                fill={stroke}
                radius={kind === 'stacked' ? 0 : [2, 2, 0, 0]}
                maxBarSize={isQuiet ? 10 : 18}
              />
            )
          })}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
