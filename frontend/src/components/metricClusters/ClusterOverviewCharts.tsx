import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { INSIGHTS_PALETTE } from '../../pages/callImports/components/InsightsMetricCard'
import type { EvaluationMetricClustersState } from './types'

const TOOLTIP_CONTENT_STYLE: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e5e7eb',
  borderRadius: 8,
  fontSize: 11,
  color: '#0f172a',
  boxShadow: '0 8px 24px rgba(15, 23, 42, 0.08)',
  padding: '6px 10px',
}

function truncateLabel(label: string, max = 28): string {
  if (label.length <= max) return label
  return `${label.slice(0, max - 1)}…`
}

function HorizontalMetricBarChart({
  title,
  subtitle,
  data,
  dataKey,
  valueFormatter,
  tooltipLabel,
}: {
  title: string
  subtitle: string
  data: Array<{ name: string; value: number; detail?: string }>
  dataKey: string
  valueFormatter: (value: number) => string
  tooltipLabel: string
}) {
  if (!data.length) return null

  const chartHeight = Math.max(140, 24 + data.length * 28)

  return (
    <article className="rounded-lg border border-gray-200 bg-white p-4 space-y-2 min-w-0">
      <div>
        <h5 className="text-sm font-semibold text-gray-900">{title}</h5>
        <p className="text-[10px] text-gray-500 mt-0.5">{subtitle}</p>
      </div>
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 16, left: 0, bottom: 4 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#f1f5f9"
            horizontal={false}
          />
          <XAxis
            type="number"
            tick={{ fontSize: 10, fill: '#64748b' }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={120}
            tick={{ fontSize: 10, fill: '#475569' }}
            axisLine={false}
            tickLine={false}
            interval={0}
            tickFormatter={(value) => truncateLabel(String(value), 18)}
          />
          <Tooltip
            contentStyle={TOOLTIP_CONTENT_STYLE}
            cursor={{ fill: 'rgba(99,102,241,0.06)' }}
            formatter={(value: number) => [valueFormatter(value), tooltipLabel]}
            labelFormatter={(label, payload) => {
              const detail = payload?.[0]?.payload?.detail
              return detail ? `${label} — ${detail}` : String(label)
            }}
          />
          <Bar dataKey={dataKey} radius={[0, 4, 4, 0]} maxBarSize={18}>
            {data.map((row, index) => (
              <Cell
                key={row.name}
                fill={INSIGHTS_PALETTE[index % INSIGHTS_PALETTE.length]}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </article>
  )
}

export default function ClusterOverviewCharts({
  state,
}: {
  state: EvaluationMetricClustersState
}) {
  const hotspotData = useMemo(() => {
    const rows = state.rca_summary?.metric_hotspots ?? []
    return [...rows]
      .sort((a, b) => b.metric_rate_pct - a.metric_rate_pct)
      .slice(0, 8)
      .map((row) => ({
        name: row.metric_name,
        value: row.metric_rate_pct,
        detail: `${row.flagged_calls.toLocaleString()} flagged calls`,
      }))
  }, [state.rca_summary?.metric_hotspots])

  const patternData = useMemo(() => {
    const rows = state.rca_summary?.repeated_patterns ?? []
    return [...rows]
      .sort((a, b) => b.evidence_share_pct - a.evidence_share_pct)
      .slice(0, 8)
      .map((row) => ({
        name: row.metric_name,
        value: row.evidence_share_pct,
        detail: row.top_rca_patterns,
      }))
  }, [state.rca_summary?.repeated_patterns])

  const clusterSizeData = useMemo(() => {
    const flattened = state.groups.flatMap((group) =>
      group.clusters.map((cluster) => ({
        name: cluster.label,
        value: cluster.count,
        detail: group.metric_name,
      })),
    )
    return flattened
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [state.groups])

  if (!hotspotData.length && !patternData.length && !clusterSizeData.length) {
    return null
  }

  return (
    <section className="space-y-3">
      <div>
        <h4 className="text-base font-semibold text-gray-900">Overview</h4>
        <p className="text-xs text-gray-600 mt-1">
          Scan failure concentration by metric, RCA pattern share, and largest
          individual clusters before drilling into tables below.
        </p>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <HorizontalMetricBarChart
          title="Metric hotspots"
          subtitle="Which metrics fail most in this scope?"
          data={hotspotData}
          dataKey="value"
          valueFormatter={(value) => `${value.toFixed(2)}%`}
          tooltipLabel="Metric rate"
        />
        <HorizontalMetricBarChart
          title="Top RCA patterns"
          subtitle="Where are clustered failure themes concentrated?"
          data={patternData}
          dataKey="value"
          valueFormatter={(value) => `${value.toFixed(1)}%`}
          tooltipLabel="Evidence share"
        />
      </div>
      {clusterSizeData.length ? (
        <HorizontalMetricBarChart
          title="Largest failure themes"
          subtitle="Biggest individual clusters by flagged call count"
          data={clusterSizeData}
          dataKey="value"
          valueFormatter={(value) => value.toLocaleString()}
          tooltipLabel="Calls"
        />
      ) : null}
    </section>
  )
}
