import { useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  CircleDot,
  PieChart as PieChartIcon,
} from 'lucide-react'
import type { CallImportInsightsMetric } from '../../../types/api'

// Shared categorical palette. Mirrors the one used on the
// per-evaluation Visualizations tab so a metric keeps the same
// visual identity across both screens.
export const INSIGHTS_PALETTE = [
  '#6366f1',
  '#10b981',
  '#f59e0b',
  '#ef4444',
  '#a855f7',
  '#0ea5e9',
  '#ec4899',
  '#14b8a6',
  '#f97316',
  '#84cc16',
]

const TOOLTIP_CONTENT_STYLE: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e5e7eb',
  borderRadius: 8,
  fontSize: 11,
  color: '#0f172a',
  boxShadow: '0 8px 24px rgba(15, 23, 42, 0.08)',
  padding: '6px 10px',
}
const TOOLTIP_LABEL_STYLE: React.CSSProperties = {
  color: '#475569',
  fontWeight: 500,
  marginBottom: 2,
}
const TOOLTIP_ITEM_STYLE: React.CSSProperties = {
  color: '#0f172a',
  fontWeight: 600,
}

type CategoricalChartOption = 'bar' | 'pie' | 'lollipop'

function truncateLabel(label: string, max = 22): string {
  if (typeof label !== 'string') return ''
  if (label.length <= max) return label
  return `${label.slice(0, max - 1)}…`
}

/**
 * Render the percent label on the coloured slice itself instead of
 * recharts' default outside placement, which clips against the
 * container edge for slices whose midpoint sits at the top or sides
 * of the donut. Tiny slices (<6%) are skipped because the arc is
 * too narrow to render legible text.
 */
function renderInsideSliceLabel(props: any) {
  const { cx, cy, midAngle, innerRadius, outerRadius, percent } = props
  if (percent == null || percent < 0.06) return null
  const RADIAN = Math.PI / 180
  const radius = innerRadius + (outerRadius - innerRadius) * 0.55
  const x = cx + radius * Math.cos(-midAngle * RADIAN)
  const y = cy + radius * Math.sin(-midAngle * RADIAN)
  return (
    <text
      x={x}
      y={y}
      fill="#fff"
      textAnchor="middle"
      dominantBaseline="central"
      fontSize={11}
      fontWeight={700}
      style={{
        pointerEvents: 'none',
        textShadow: '0 1px 2px rgba(0,0,0,0.18)',
      }}
    >
      {`${Math.round(percent * 100)}%`}
    </text>
  )
}

function formatDelta(delta: number, suffix = ''): string {
  const sign = delta > 0 ? '+' : ''
  return `${sign}${delta.toFixed(2)}${suffix}`
}

/**
 * A single insight card rendered inside the call import "Insights"
 * tab. Numeric metrics get a gradient-filled area chart with a
 * prominent latest mean and a coloured delta badge; categorical
 * metrics get a chart-type picker (bar / pie / lollipop) and use the
 * shared palette so labels keep their identity across runs.
 */
export default function InsightsMetricCard({
  metric,
}: {
  metric: CallImportInsightsMetric
}) {
  const [chartType, setChartType] = useState<CategoricalChartOption>('lollipop')

  const latest = metric.latest
  const trendData = useMemo(
    () =>
      metric.trend
        .filter((p) => p.mean !== null)
        .map((p) => ({
          x: new Date(p.created_at).toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
          }),
          mean: p.mean as number,
          name: p.name ?? '',
          completed: p.completed_rows,
        })),
    [metric.trend],
  )

  const valueCounts = useMemo(() => {
    if (!latest) return []
    return [...latest.value_counts].sort((a, b) => b.count - a.count)
  }, [latest])
  const totalCategorical = valueCounts.reduce((s, v) => s + v.count, 0)

  const hasNumericTrend = trendData.length > 1
  const hasCategorical = valueCounts.length > 0
  const isMultiLabel = latest?.is_multi_label_parent === true

  // Numeric trend direction: compare first vs last mean to colour the
  // header badge. We treat a flat run (Δ < 0.005) as neutral so noisy
  // metrics don't look like they're constantly improving / regressing.
  const delta =
    hasNumericTrend &&
    trendData[0].mean != null &&
    trendData[trendData.length - 1].mean != null
      ? (trendData[trendData.length - 1].mean as number) -
        (trendData[0].mean as number)
      : 0
  const deltaTone: 'good' | 'bad' | 'flat' =
    Math.abs(delta) < 0.005 ? 'flat' : delta > 0 ? 'good' : 'bad'
  const DeltaIcon =
    deltaTone === 'good'
      ? ArrowUpRight
      : deltaTone === 'bad'
        ? ArrowDownRight
        : ArrowRight
  const deltaClass =
    deltaTone === 'good'
      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
      : deltaTone === 'bad'
        ? 'bg-rose-50 text-rose-700 border-rose-200'
        : 'bg-gray-50 text-gray-600 border-gray-200'

  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm hover:shadow-md transition-shadow p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p
            className="text-sm font-semibold text-gray-900 truncate"
            title={metric.metric_name}
          >
            {metric.metric_name}
          </p>
          <div className="mt-1 flex items-center gap-1.5 flex-wrap">
            {metric.metric_type && (
              <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary-50 text-primary-700 capitalize">
                {metric.metric_type}
              </span>
            )}
            {isMultiLabel && (
              <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-violet-50 text-violet-700">
                Multi-label
              </span>
            )}
            {latest && (
              <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-700">
                n = {latest.count}
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          {latest?.mean != null && (
            <div className="text-right">
              <p className="text-[9px] uppercase tracking-wider text-gray-500">
                Latest mean
              </p>
              <p className="text-lg font-semibold text-primary-700 leading-none tabular-nums">
                {latest.mean.toFixed(2)}
              </p>
            </div>
          )}
          {hasNumericTrend && (
            <span
              className={`inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full border ${deltaClass}`}
              title={`Change since first run (${formatDelta(delta)})`}
            >
              <DeltaIcon className="h-3 w-3" />
              {formatDelta(delta)}
            </span>
          )}
        </div>
      </div>

      {hasNumericTrend ? (
        <NumericTrendChart data={trendData} metricId={metric.metric_id} />
      ) : hasCategorical ? (
        <>
          <div className="flex justify-end">
            <CategoricalChartPicker
              value={chartType}
              onChange={setChartType}
            />
          </div>
          <CategoricalChart
            chartType={chartType}
            valueCounts={valueCounts}
            totalCategorical={totalCategorical}
            metricId={metric.metric_id}
          />
        </>
      ) : (
        <p className="text-xs text-gray-400 italic py-6 text-center">
          {trendData.length === 1
            ? 'Need at least two runs to plot a trend.'
            : 'No data recorded yet.'}
        </p>
      )}

      {latest && (
        <div className="grid grid-cols-4 gap-2 pt-2 border-t border-gray-100">
          {latest.mean != null ? (
            <>
              <Stat label="n" value={latest.count} />
              <Stat label="Mean" value={latest.mean.toFixed(2)} />
              <Stat
                label="Best"
                value={latest.max != null ? latest.max.toFixed(2) : '—'}
                tone="good"
                title="Highest single-row score in the latest run"
              />
              <Stat
                label="σ"
                value={
                  latest.stddev != null ? latest.stddev.toFixed(2) : '—'
                }
                title="Standard deviation — lower is more consistent"
              />
            </>
          ) : valueCounts.length > 0 ? (
            <>
              <Stat label="n" value={latest.count} />
              <Stat
                label="Labels"
                value={valueCounts.length}
                title="Distinct labels observed"
              />
              <Stat
                label="Top"
                value={truncateLabel(valueCounts[0]?.label ?? '—', 10)}
                title={valueCounts[0]?.label ?? ''}
              />
              <Stat
                label="Top %"
                value={`${Math.round(
                  ((valueCounts[0]?.count ?? 0) /
                    Math.max(totalCategorical, 1)) *
                    100,
                )}%`}
                title="Share of rows where the dominant label fired"
              />
            </>
          ) : (
            <Stat label="n" value={latest.count} />
          )}
        </div>
      )}
    </div>
  )
}

function Stat({
  label,
  value,
  title,
  tone,
}: {
  label: string
  value: string | number
  title?: string
  tone?: 'good' | 'bad' | 'neutral'
}) {
  const valueClass =
    tone === 'good'
      ? 'text-emerald-700'
      : tone === 'bad'
        ? 'text-rose-700'
        : 'text-gray-900'
  return (
    <div className="text-center" title={title}>
      <p className="text-[9px] uppercase tracking-wider text-gray-500">
        {label}
      </p>
      <p className={`text-xs font-semibold tabular-nums ${valueClass}`}>
        {value}
      </p>
    </div>
  )
}

function CategoricalChartPicker({
  value,
  onChange,
}: {
  value: CategoricalChartOption
  onChange: (v: CategoricalChartOption) => void
}) {
  const options: { id: CategoricalChartOption; Icon: any; title: string }[] = [
    { id: 'lollipop', Icon: CircleDot, title: 'Lollipop (default)' },
    { id: 'bar', Icon: BarChart3, title: 'Horizontal bar' },
    { id: 'pie', Icon: PieChartIcon, title: 'Donut' },
  ]
  return (
    <div className="inline-flex items-center gap-0.5 rounded-md border border-gray-200 bg-gray-50/70 p-0.5">
      {options.map((opt) => {
        const Icon = opt.Icon
        const active = value === opt.id
        return (
          <button
            key={opt.id}
            type="button"
            title={opt.title}
            aria-pressed={active}
            onClick={() => onChange(opt.id)}
            className={`p-1 rounded transition ${
              active
                ? 'bg-white text-primary-700 shadow-sm'
                : 'text-gray-500 hover:text-gray-800 hover:bg-white/70'
            }`}
          >
            <Icon className="h-3 w-3" />
          </button>
        )
      })}
    </div>
  )
}

// --- Numeric trend ------------------------------------------------------
function NumericTrendChart({
  data,
  metricId,
}: {
  data: { x: string; mean: number; name: string }[]
  metricId: string
}) {
  return (
    <ResponsiveContainer width="100%" height={140}>
      <AreaChart
        data={data}
        margin={{ top: 8, right: 8, left: -16, bottom: 0 }}
      >
        <defs>
          <linearGradient
            id={`insight-area-${metricId}`}
            x1="0"
            y1="0"
            x2="0"
            y2="1"
          >
            <stop offset="0%" stopColor="#6366f1" stopOpacity={0.4} />
            <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="#f1f5f9"
          vertical={false}
        />
        <XAxis
          dataKey="x"
          tick={{ fontSize: 10, fill: '#64748b' }}
          axisLine={{ stroke: '#e2e8f0' }}
          tickLine={false}
          minTickGap={20}
        />
        <YAxis
          tick={{ fontSize: 10, fill: '#64748b' }}
          axisLine={false}
          tickLine={false}
          width={36}
        />
        <Tooltip
          contentStyle={TOOLTIP_CONTENT_STYLE}
          labelStyle={TOOLTIP_LABEL_STYLE}
          itemStyle={TOOLTIP_ITEM_STYLE}
          formatter={(value: any) => [Number(value).toFixed(2), 'Mean']}
          labelFormatter={(_label, payload: any) => {
            const name = payload?.[0]?.payload?.name
            const date = payload?.[0]?.payload?.x
            return name ? `${date} · ${name}` : date
          }}
        />
        <Area
          type="monotone"
          dataKey="mean"
          stroke="#6366f1"
          strokeWidth={2}
          fill={`url(#insight-area-${metricId})`}
          dot={{ r: 3, stroke: '#6366f1', strokeWidth: 2, fill: '#fff' }}
          activeDot={{ r: 4, fill: '#6366f1' }}
          isAnimationActive
          animationDuration={400}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// --- Categorical -------------------------------------------------------
function CategoricalChart({
  chartType,
  valueCounts,
  totalCategorical,
  metricId,
}: {
  chartType: CategoricalChartOption
  valueCounts: { label: string; count: number }[]
  totalCategorical: number
  metricId: string
}) {
  if (chartType === 'pie') {
    const top = valueCounts[0]
    const topShare = top
      ? top.count / Math.max(totalCategorical, 1)
      : 0
    return (
      <div className="relative">
        <ResponsiveContainer width="100%" height={210}>
          <PieChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
            <Tooltip
              contentStyle={TOOLTIP_CONTENT_STYLE}
              labelStyle={TOOLTIP_LABEL_STYLE}
              itemStyle={TOOLTIP_ITEM_STYLE}
              formatter={(value: any, name: any) => [`${value} rows`, name]}
            />
            <Pie
              data={valueCounts}
              dataKey="count"
              nameKey="label"
              innerRadius={50}
              outerRadius={82}
              paddingAngle={2}
              stroke="#fff"
              strokeWidth={2}
              isAnimationActive
              animationDuration={400}
              label={renderInsideSliceLabel}
              labelLine={false}
            >
              {valueCounts.map((vc, i) => (
                <Cell
                  key={vc.label}
                  fill={INSIGHTS_PALETTE[i % INSIGHTS_PALETTE.length]}
                />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        {top && (
          <div
            className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center"
            style={{ paddingInline: 12 }}
          >
            <p className="text-[9px] uppercase tracking-wider text-gray-500 leading-tight">
              Top
            </p>
            <p
              className="text-[11px] font-semibold text-gray-900 max-w-[80px] truncate leading-tight mt-0.5"
              title={top.label}
            >
              {truncateLabel(top.label, 10)}
            </p>
            <p className="text-[12px] font-bold text-primary-700 leading-tight mt-0.5 tabular-nums">
              {Math.round(topShare * 100)}%
            </p>
          </div>
        )}
      </div>
    )
  }

  if (chartType === 'lollipop') {
    return (
      <ResponsiveContainer
        width="100%"
        height={Math.max(140, 24 + valueCounts.length * 26)}
      >
        <BarChart
          data={valueCounts}
          layout="vertical"
          margin={{ top: 4, right: 24, left: 0, bottom: 4 }}
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
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="label"
            tick={{ fontSize: 11, fill: '#334155' }}
            axisLine={false}
            tickLine={false}
            width={140}
            interval={0}
            tickFormatter={(v: string) => truncateLabel(v, 22)}
          />
          <Tooltip
            contentStyle={TOOLTIP_CONTENT_STYLE}
            labelStyle={TOOLTIP_LABEL_STYLE}
            itemStyle={TOOLTIP_ITEM_STYLE}
            cursor={{ fill: 'rgba(99,102,241,0.06)' }}
            formatter={(value: any) => [`${value} rows`, 'Count']}
          />
          <Bar
            dataKey="count"
            shape={(props: any) => {
              const { x, y, width, height, fill } = props
              const cy = (y ?? 0) + (height ?? 0) / 2
              const w = Math.max(0, width ?? 0)
              return (
                <g>
                  <rect
                    x={x}
                    y={cy - 1}
                    width={w}
                    height={2}
                    fill={fill}
                    opacity={0.5}
                  />
                  <circle cx={(x ?? 0) + w} cy={cy} r={5} fill={fill} />
                </g>
              )
            }}
            isAnimationActive
            animationDuration={400}
          >
            {valueCounts.map((vc, i) => (
              <Cell
                key={vc.label}
                fill={INSIGHTS_PALETTE[i % INSIGHTS_PALETTE.length]}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    )
  }

  return (
    <ResponsiveContainer
      width="100%"
      height={Math.max(140, 24 + valueCounts.length * 28)}
    >
      <BarChart
        data={valueCounts}
        layout="vertical"
        margin={{ top: 4, right: 24, left: 0, bottom: 4 }}
      >
        <defs>
          <linearGradient
            id={`insight-bar-${metricId}`}
            x1="0"
            y1="0"
            x2="1"
            y2="0"
          >
            <stop offset="0%" stopColor="#6366f1" stopOpacity={0.55} />
            <stop offset="100%" stopColor="#6366f1" stopOpacity={0.95} />
          </linearGradient>
        </defs>
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
          allowDecimals={false}
        />
        <YAxis
          type="category"
          dataKey="label"
          tick={{ fontSize: 11, fill: '#334155' }}
          axisLine={false}
          tickLine={false}
          width={140}
          interval={0}
          tickFormatter={(v: string) => truncateLabel(v, 22)}
        />
        <Tooltip
          contentStyle={TOOLTIP_CONTENT_STYLE}
          labelStyle={TOOLTIP_LABEL_STYLE}
          itemStyle={TOOLTIP_ITEM_STYLE}
          cursor={{ fill: 'rgba(99,102,241,0.06)' }}
          formatter={(value: any) => [`${value} rows`, 'Count']}
        />
        <Bar
          dataKey="count"
          fill={`url(#insight-bar-${metricId})`}
          radius={[0, 4, 4, 0]}
          isAnimationActive
          animationDuration={400}
        />
      </BarChart>
    </ResponsiveContainer>
  )
}
