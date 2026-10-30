import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AGENT_COLORS, CHART_PALETTE } from '../dashboardSection'

export default function HorizontalStackedBar({
  rows,
  series,
  onBarClick,
  height,
}: {
  rows: Array<Record<string, string | number>>
  series: Array<{ key: string; label: string; color?: string }>
  onBarClick?: (rowName: string) => void
  height?: number
}) {
  const chartHeight = height ?? Math.max(120, rows.length * 36 + 24)
  return (
    <div style={{ height: chartHeight }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart layout="vertical" data={rows} margin={{ top: 4, right: 12, left: 4, bottom: 4 }}>
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="name"
            width={128}
            tick={{ fontSize: 11, fill: '#4b5563' }}
          />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: '#e5e7eb' }}
            formatter={(value, name) => [typeof value === 'number' ? Number(value.toFixed(2)) : value, name]}
          />
          {series.map((item, index) => (
            <Bar
              key={item.key}
              dataKey={item.key}
              name={item.label}
              stackId="a"
              fill={item.color ?? AGENT_COLORS[item.key] ?? CHART_PALETTE[index % CHART_PALETTE.length]}
              cursor={onBarClick ? 'pointer' : undefined}
              onClick={(data) => {
                const name = (data as { name?: string })?.name
                if (name) onBarClick?.(name)
              }}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
