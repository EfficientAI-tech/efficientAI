import { useState, type CSSProperties } from 'react'
import {
  BarChart3,
  CircleDot,
  Grid3x3,
  LayoutGrid,
  PieChart as PieChartIcon,
  Target,
  TrendingUp,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  Line,
  LineChart,
  Pie,
  PieChart,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
  Treemap,
  XAxis,
  YAxis,
} from 'recharts'
import type { CallImportMetricAggregate } from '../../../../types/api'
import {
  PIE_COLORS,
  autoPickCategoricalChart,
  type CategoricalChartType,
} from './chartPrefs'

// Light-themed tooltip styling shared by every recharts ``Tooltip``
// on this page. Replaces the previous dark navy backdrop which made
// the hovered number hard to read against most page colors.
export const CHART_TOOLTIP_STYLE: CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e5e7eb',
  borderRadius: 8,
  fontSize: 11,
  color: '#0f172a',
  boxShadow: '0 8px 24px rgba(15, 23, 42, 0.08)',
  padding: '6px 10px',
}
export const CHART_TOOLTIP_LABEL_STYLE: CSSProperties = {
  color: '#475569',
  fontWeight: 500,
  marginBottom: 2,
}
export const CHART_TOOLTIP_ITEM_STYLE: CSSProperties = {
  color: '#0f172a',
  fontWeight: 600,
}

/**
 * Available categorical chart types for a given metric. Multi-label
 * parents get the heatmap + cumulative coverage extras; everything
 * else gets the pie/donut option (which would mislead on multi-label
 * because slices wouldn't sum to 100%). The picker uses this to grey
 * out icons that don't apply.
 */
export function availableChartTypesFor(
  metric: CallImportMetricAggregate,
): CategoricalChartType[] {
  const isMulti = metric.is_multi_label_parent === true
  const base: CategoricalChartType[] = ['bar', 'lollipop', 'treemap']
  if (!isMulti) {
    base.push('pie', 'radial', 'waffle')
  }
  if (isMulti) {
    base.push('coverage', 'heatmap')
  }
  return base
}

const CHART_TYPE_META: Record<
  CategoricalChartType,
  { label: string; Icon: React.ComponentType<{ className?: string }> }
> = {
  pie: { label: 'Pie / donut', Icon: PieChartIcon },
  bar: { label: 'Horizontal bar', Icon: BarChart3 },
  lollipop: { label: 'Lollipop', Icon: CircleDot },
  radial: { label: 'Radial bar', Icon: Target },
  treemap: { label: 'Treemap', Icon: LayoutGrid },
  waffle: { label: 'Waffle (10×10)', Icon: Grid3x3 },
  coverage: { label: 'Cumulative coverage', Icon: TrendingUp },
  heatmap: { label: 'Co-occurrence heatmap', Icon: Grid3x3 },
}

/**
 * Compact icon-row picker rendered top-right of every chart card.
 * Clicking a non-active icon overrides the per-metric chart type;
 * clicking the already-active icon when an override is present
 * reverts to the global default ("auto").
 */
export function CategoricalChartPicker({
  metric,
  active,
  overridden,
  onChange,
}: {
  metric: CallImportMetricAggregate
  active: CategoricalChartType
  overridden: boolean
  onChange: (type: CategoricalChartType | null) => void
}) {
  const types = availableChartTypesFor(metric)
  return (
    <div className="inline-flex items-center gap-0.5 rounded-md border border-gray-200 bg-gray-50/70 p-0.5">
      {types.map((t) => {
        const meta = CHART_TYPE_META[t]
        const Icon = meta.Icon
        const isActive = active === t
        return (
          <button
            key={t}
            type="button"
            title={meta.label}
            aria-pressed={isActive}
            onClick={() => {
              if (isActive && overridden) onChange(null)
              else onChange(t)
            }}
            className={`p-1 rounded transition ${
              isActive
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

/**
 * Sort categorical value counts desc by count so every chart type
 * renders the most-impactful labels first. Backend already does this
 * for the categorical aggregator, but defensive sorting keeps the
 * frontend correct if a future code path returns unsorted data.
 */
export function sortValueCounts(
  counts: CallImportMetricAggregate['value_counts'],
): CallImportMetricAggregate['value_counts'] {
  return [...counts].sort((a, b) => b.count - a.count)
}

/**
 * Truncate a long categorical label so it fits inside a tooltip /
 * tile / legend slot. The full text is always available via the
 * surrounding ``title`` attribute or tooltip content.
 */
function truncateLabel(label: string, max = 24): string {
  if (typeof label !== 'string') return ''
  if (label.length <= max) return label
  return `${label.slice(0, max - 1)}…`
}

/**
 * Side-legend below the chart. Every category is clickable so the
 * user can drill in even when the chart itself is hard to click
 * (e.g. tiny treemap tiles or thin pie slices). Defaults to showing
 * the top 6 with a "Show all" toggle so a long-tail metric doesn't
 * dominate the card vertically.
 */
export function CategoryLegend({
  valueCounts,
  totalCategorical,
  activeValue,
  onValueClick,
}: {
  valueCounts: CallImportMetricAggregate['value_counts']
  totalCategorical: number
  activeValue: string | null
  onValueClick: (value: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const COLLAPSED_LIMIT = 6
  const visible =
    expanded || valueCounts.length <= COLLAPSED_LIMIT
      ? valueCounts
      : valueCounts.slice(0, COLLAPSED_LIMIT)
  const hidden = valueCounts.length - visible.length
  return (
    <div className="mt-3 text-[11px]">
      <ul className="space-y-1">
        {visible.map((vc, i) => {
          const pct = (vc.count / totalCategorical) * 100
          const isFiltered = activeValue === vc.label
          return (
            <li key={vc.label}>
              <button
                type="button"
                onClick={() => onValueClick(vc.label)}
                className={`group/row w-full flex items-center gap-2 rounded px-1.5 py-1 transition ${
                  isFiltered
                    ? 'bg-primary-50 text-primary-800'
                    : 'hover:bg-gray-50 text-gray-700'
                }`}
              >
                <span
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{ background: PIE_COLORS[i % PIE_COLORS.length] }}
                />
                <span
                  className="text-left flex-1 break-words"
                  title={vc.label}
                >
                  {vc.label}
                </span>
                <span className="font-medium text-gray-900 tabular-nums">
                  {vc.count}
                </span>
                <span className="text-gray-400 w-10 text-right tabular-nums">
                  {pct.toFixed(0)}%
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-1 text-[10px] text-primary-600 hover:text-primary-800 px-1.5"
        >
          Show {hidden} more
        </button>
      )}
      {expanded && valueCounts.length > COLLAPSED_LIMIT && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="mt-1 text-[10px] text-gray-500 hover:text-gray-700 px-1.5"
        >
          Show less
        </button>
      )}
    </div>
  )
}

/**
 * Custom Y-axis tick for the horizontal categorical charts (lollipop
 * and ranked bar). Sizes its truncation to the column width the
 * caller passes via ``colWidth`` (recharts itself does not forward
 * the YAxis ``width`` prop into custom tick components, so we plumb
 * it explicitly) and exposes the full text via an SVG ``<title>``
 * so hovering a clipped row reveals the original label. Long labels
 * also drop one font size so we squeeze in a few extra characters
 * before having to clip.
 */
function LongLabelTick(props: any) {
  const { x, y, payload, colWidth } = props
  const value: string = String(payload?.value ?? '')
  const slot = typeof colWidth === 'number' && colWidth > 0 ? colWidth : 200
  const fontSize = value.length > 22 ? 10 : 11
  const charPx = fontSize * 0.58
  const maxChars = Math.max(8, Math.floor((slot - 12) / charPx))
  const display =
    value.length > maxChars ? `${value.slice(0, maxChars - 1)}…` : value
  return (
    <g transform={`translate(${x},${y})`}>
      <title>{value}</title>
      <text
        x={-6}
        y={0}
        dy={4}
        textAnchor="end"
        fill="#334155"
        fontSize={fontSize}
      >
        {display}
      </text>
    </g>
  )
}

type ValueCount = CallImportMetricAggregate['value_counts'][number]

interface CategoricalChartProps {
  metric: CallImportMetricAggregate
  chartType: CategoricalChartType
  valueCounts: ValueCount[]
  totalCategorical: number
  activeValue: string | null
  onValueClick: (value: string) => void
}

/**
 * Routes the categorical render to the right chart sub-component.
 * Each sub-component owns its layout/sizing/animation but shares the
 * tooltip styling and click-to-filter contract.
 */
export function CategoricalChart(props: CategoricalChartProps) {
  const { metric, chartType, valueCounts } = props

  // Defensive fallback: a chart type that doesn't apply to this
  // metric (e.g. heatmap on a single-value metric) auto-promotes to
  // the next-best fit. Prevents a stale localStorage preference from
  // leaving the card empty when a metric type changes.
  const safeType: CategoricalChartType = (() => {
    const allowed = availableChartTypesFor(metric)
    if (allowed.includes(chartType)) return chartType
    if (metric.is_multi_label_parent) return 'bar'
    return autoPickCategoricalChart(metric)
  })()

  if (!valueCounts.length) return null

  switch (safeType) {
    case 'pie':
      return <CategoricalPieChart {...props} />
    case 'bar':
      return <CategoricalBarChart {...props} />
    case 'lollipop':
      return <CategoricalLollipopChart {...props} />
    case 'radial':
      return <CategoricalRadialChart {...props} />
    case 'treemap':
      return <CategoricalTreemapChart {...props} />
    case 'waffle':
      return <CategoricalWaffleChart {...props} />
    case 'coverage':
      return <CategoricalCoverageChart {...props} />
    case 'heatmap':
      return <CategoricalHeatmapChart {...props} />
    default:
      return <CategoricalBarChart {...props} />
  }
}

// --- Pie / donut --------------------------------------------------------
//
// Donut variant: hole in the middle keeps the center available for a
// summary stat (top label / share). Slice labels are rendered at the
// pie midpoint with a leader-line guard — small slices (<5%) drop the
// label so they don't pile up on top of each other.
function CategoricalPieChart({
  valueCounts,
  totalCategorical,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  const top = valueCounts[0]
  const topShare = top ? top.count / Math.max(totalCategorical, 1) : 0
  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={240}>
        <PieChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <Tooltip
            contentStyle={CHART_TOOLTIP_STYLE}
            labelStyle={CHART_TOOLTIP_LABEL_STYLE}
            itemStyle={CHART_TOOLTIP_ITEM_STYLE}
            formatter={(value: any, name: any) => [`${value} rows`, name]}
          />
          <Pie
            data={valueCounts}
            dataKey="count"
            nameKey="label"
            innerRadius={56}
            outerRadius={92}
            paddingAngle={2}
            stroke="#fff"
            strokeWidth={2}
            isAnimationActive
            animationDuration={400}
            onClick={(slice: any) => {
              const label = slice?.payload?.label ?? slice?.name
              if (typeof label === 'string') onValueClick(label)
            }}
            label={renderInsideSliceLabel}
            labelLine={false}
          >
            {valueCounts.map((vc, i) => (
              <Cell
                key={vc.label}
                fill={PIE_COLORS[i % PIE_COLORS.length]}
                cursor="pointer"
                opacity={
                  activeValue && activeValue !== vc.label ? 0.35 : 1
                }
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
            className="text-[11px] font-semibold text-gray-900 max-w-[88px] truncate leading-tight mt-0.5"
            title={top.label}
          >
            {truncateLabel(top.label, 12)}
          </p>
          <p className="text-[13px] font-bold text-primary-700 leading-tight mt-0.5 tabular-nums">
            {Math.round(topShare * 100)}%
          </p>
        </div>
      )}
    </div>
  )
}

/**
 * Custom Pie ``label`` renderer that places the percent text on the
 * coloured slice itself (between ``innerRadius`` and ``outerRadius``)
 * rather than at the default outside position. The default placement
 * overflows the container on slices whose midpoint sits near the top
 * or sides of the chart and gets clipped by the SVG boundary; placing
 * the label on the ring keeps it visible at every slice angle.
 *
 * Slices below 6% are hidden because the arc is too thin to render
 * legible text — the side legend below the chart already exposes
 * those values.
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
      style={{ pointerEvents: 'none', textShadow: '0 1px 2px rgba(0,0,0,0.18)' }}
    >
      {`${Math.round(percent * 100)}%`}
    </text>
  )
}

// --- Bar (horizontal, ranked) -------------------------------------------
function CategoricalBarChart({
  metric,
  valueCounts,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  const longestLabel = valueCounts.reduce(
    (m, v) => Math.max(m, v.label.length),
    0,
  )
  const yAxisWidth = Math.min(260, Math.max(160, longestLabel * 7 + 24))
  return (
    <ResponsiveContainer
      width="100%"
      height={Math.max(180, 36 + valueCounts.length * 36)}
    >
      <BarChart
        data={valueCounts}
        layout="vertical"
        margin={{ top: 8, right: 32, left: 0, bottom: 8 }}
      >
        <defs>
          <linearGradient
            id={`bar-cat-${metric.metric_id}`}
            x1="0"
            y1="0"
            x2="1"
            y2="0"
          >
            <stop offset="0%" stopColor="#10b981" stopOpacity={0.55} />
            <stop offset="100%" stopColor="#10b981" stopOpacity={0.95} />
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
          tick={(p: any) => <LongLabelTick {...p} colWidth={yAxisWidth} />}
          axisLine={false}
          tickLine={false}
          width={yAxisWidth}
          interval={0}
        />
        <Tooltip
          contentStyle={CHART_TOOLTIP_STYLE}
          labelStyle={CHART_TOOLTIP_LABEL_STYLE}
          itemStyle={CHART_TOOLTIP_ITEM_STYLE}
          cursor={{ fill: 'rgba(16,185,129,0.08)' }}
          formatter={(value: any) => [`${value} rows`, 'Count']}
        />
        <Bar
          dataKey="count"
          fill={`url(#bar-cat-${metric.metric_id})`}
          radius={[0, 4, 4, 0]}
          isAnimationActive
          animationDuration={400}
          onClick={(bar: any) => {
            const label = bar?.label ?? bar?.payload?.label
            if (typeof label === 'string') onValueClick(label)
          }}
        >
          {valueCounts.map((vc) => (
            <Cell
              key={vc.label}
              cursor="pointer"
              opacity={activeValue && activeValue !== vc.label ? 0.35 : 1}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// --- Lollipop -----------------------------------------------------------
//
// Custom Bar shape draws a thin horizontal stick + a circle end-cap
// for each row. Visually lighter than a full bar and reads as a
// ranked top-N list at a glance.
function LollipopShape(props: any) {
  const { x, y, width, height, fill } = props
  const cy = (y ?? 0) + (height ?? 0) / 2
  const stickH = 2
  const r = 5
  const safeWidth = Math.max(0, width ?? 0)
  return (
    <g>
      <rect
        x={x}
        y={cy - stickH / 2}
        width={safeWidth}
        height={stickH}
        fill={fill}
        opacity={0.5}
      />
      <circle cx={(x ?? 0) + safeWidth} cy={cy} r={r} fill={fill} />
    </g>
  )
}

function CategoricalLollipopChart({
  valueCounts,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  // Sized so the longest label gets all the space it can, capped at
  // ~45% of the typical card width (cards are 480-560px wide in the
  // 2-up grid, so 240 leaves ~240-320 for the bars themselves).
  const longestLabel = valueCounts.reduce(
    (m, v) => Math.max(m, v.label.length),
    0,
  )
  const yAxisWidth = Math.min(260, Math.max(160, longestLabel * 7 + 24))
  return (
    <ResponsiveContainer
      width="100%"
      height={Math.max(180, 28 + valueCounts.length * 30)}
    >
      <BarChart
        data={valueCounts}
        layout="vertical"
        margin={{ top: 8, right: 40, left: 0, bottom: 8 }}
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
          tick={(p: any) => <LongLabelTick {...p} colWidth={yAxisWidth} />}
          axisLine={false}
          tickLine={false}
          width={yAxisWidth}
          interval={0}
        />
        <Tooltip
          contentStyle={CHART_TOOLTIP_STYLE}
          labelStyle={CHART_TOOLTIP_LABEL_STYLE}
          itemStyle={CHART_TOOLTIP_ITEM_STYLE}
          cursor={{ fill: 'rgba(99,102,241,0.06)' }}
          formatter={(value: any) => [`${value} rows`, 'Count']}
        />
        <Bar
          dataKey="count"
          shape={<LollipopShape />}
          isAnimationActive
          animationDuration={400}
          onClick={(bar: any) => {
            const label = bar?.label ?? bar?.payload?.label
            if (typeof label === 'string') onValueClick(label)
          }}
        >
          {valueCounts.map((vc, i) => (
            <Cell
              key={vc.label}
              fill={PIE_COLORS[i % PIE_COLORS.length]}
              cursor="pointer"
              opacity={activeValue && activeValue !== vc.label ? 0.35 : 1}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// --- Radial bar ---------------------------------------------------------
//
// Concentric rings, one per category. The angular extent of each
// ring encodes the count; combined with the colored side legend
// below the chart this is a punchy alternative to the donut for 3-8
// categories.
function CategoricalRadialChart({
  valueCounts,
  totalCategorical,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  const data = valueCounts.map((vc, i) => ({
    ...vc,
    fill: PIE_COLORS[i % PIE_COLORS.length],
  }))
  const max = Math.max(...valueCounts.map((v) => v.count), 1)
  return (
    <ResponsiveContainer width="100%" height={220}>
      <RadialBarChart
        innerRadius="20%"
        outerRadius="100%"
        barSize={12}
        startAngle={90}
        endAngle={-270}
        data={data}
      >
        <PolarAngleAxis
          type="number"
          domain={[0, max]}
          dataKey="count"
          tick={false}
        />
        <RadialBar
          dataKey="count"
          background={{ fill: '#f1f5f9' }}
          cornerRadius={6}
          isAnimationActive
          animationDuration={400}
          onClick={(bar: any) => {
            const label = bar?.label ?? bar?.payload?.label
            if (typeof label === 'string') onValueClick(label)
          }}
        >
          {data.map((vc) => (
            <Cell
              key={vc.label}
              fill={vc.fill}
              cursor="pointer"
              opacity={activeValue && activeValue !== vc.label ? 0.35 : 1}
            />
          ))}
        </RadialBar>
        <Tooltip
          contentStyle={CHART_TOOLTIP_STYLE}
          labelStyle={CHART_TOOLTIP_LABEL_STYLE}
          itemStyle={CHART_TOOLTIP_ITEM_STYLE}
          formatter={(value: any, _name: any, payload: any) => {
            const label = payload?.payload?.label ?? '—'
            const share = (Number(value) / Math.max(totalCategorical, 1)) * 100
            return [`${value} rows (${share.toFixed(0)}%)`, label]
          }}
        />
      </RadialBarChart>
    </ResponsiveContainer>
  )
}

// --- Treemap ------------------------------------------------------------
//
// Area-encoded categorical view that gracefully scales to many
// labels without overflowing axis space. Each tile is colored by
// rank in the same palette and shows the label + count when the
// tile is wide enough; small tiles fall back to count-only.
function CategoricalTreemapChart({
  valueCounts,
  totalCategorical,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  const data = valueCounts.map((vc, i) => ({
    name: vc.label,
    size: vc.count,
    label: vc.label,
    count: vc.count,
    fill: PIE_COLORS[i % PIE_COLORS.length],
  }))
  return (
    <div>
      <ResponsiveContainer width="100%" height={240}>
        <Treemap
          data={data}
          dataKey="size"
          stroke="#fff"
          isAnimationActive
          animationDuration={400}
          content={
            <TreemapTile
              activeValue={activeValue}
              total={totalCategorical}
              onValueClick={onValueClick}
            />
          }
        />
      </ResponsiveContainer>
    </div>
  )
}

function TreemapTile(props: any) {
  const {
    x,
    y,
    width,
    height,
    name,
    payload,
    activeValue,
    total,
    onValueClick,
  } = props
  const fill = payload?.fill ?? '#94a3b8'
  const count = payload?.count ?? 0
  const isActive = activeValue && activeValue === name
  const dimmed = activeValue && !isActive
  if (!width || !height) return null
  const showLabel = width > 70 && height > 32
  const showCount = width > 36 && height > 20
  const share = total > 0 ? (count / total) * 100 : 0
  return (
    <g
      style={{ cursor: 'pointer' }}
      onClick={() => {
        if (typeof name === 'string') onValueClick(name)
      }}
    >
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        style={{
          fill,
          stroke: '#fff',
          strokeWidth: 2,
          opacity: dimmed ? 0.35 : 1,
        }}
      />
      {showLabel ? (
        <>
          <text
            x={x + 8}
            y={y + 18}
            fill="#fff"
            fontSize={11}
            fontWeight={600}
            style={{ pointerEvents: 'none' }}
          >
            {truncateLabel(String(name ?? ''), Math.floor(width / 7))}
          </text>
          <text
            x={x + 8}
            y={y + 32}
            fill="#fff"
            fontSize={10}
            opacity={0.85}
            style={{ pointerEvents: 'none' }}
          >
            {count} · {share.toFixed(0)}%
          </text>
        </>
      ) : showCount ? (
        <text
          x={x + width / 2}
          y={y + height / 2 + 4}
          textAnchor="middle"
          fill="#fff"
          fontSize={11}
          fontWeight={600}
          style={{ pointerEvents: 'none' }}
        >
          {count}
        </text>
      ) : null}
    </g>
  )
}

// --- Waffle / 10x10 dot grid -------------------------------------------
//
// Pure SVG, no recharts. 100 squares total proportionally allocated
// to each category by largest-remainder. Reads as "X out of 100
// calls", which non-technical users find more concrete than a pie.
function CategoricalWaffleChart({
  valueCounts,
  totalCategorical,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  const total = totalCategorical || 1
  // Largest-remainder allocation so the rounded squares always sum
  // to exactly 100. Tiny categories that round to 0 squares still
  // appear in the legend.
  const ideal = valueCounts.map((vc) => (vc.count / total) * 100)
  const floors = ideal.map((v) => Math.floor(v))
  const allocated = floors.reduce((s, v) => s + v, 0)
  let remainder = 100 - allocated
  const remainders = ideal
    .map((v, i) => ({ i, frac: v - Math.floor(v) }))
    .sort((a, b) => b.frac - a.frac)
  const allocations = [...floors]
  for (const r of remainders) {
    if (remainder <= 0) break
    allocations[r.i] += 1
    remainder -= 1
  }

  // Flatten to 100 entries, each tagged with its category index.
  const cells: { catIdx: number; label: string; count: number }[] = []
  allocations.forEach((n, idx) => {
    for (let k = 0; k < n; k++) {
      cells.push({
        catIdx: idx,
        label: valueCounts[idx].label,
        count: valueCounts[idx].count,
      })
    }
  })

  const size = 16
  const gap = 3
  const cols = 10
  const rows = 10
  const w = cols * (size + gap) - gap
  const h = rows * (size + gap) - gap

  return (
    <div className="flex justify-center py-2">
      <svg width={w} height={h} role="img" aria-label="Waffle chart">
        {Array.from({ length: 100 }, (_, i) => {
          const cell = cells[i]
          const r = Math.floor(i / cols)
          const c = i % cols
          const x = c * (size + gap)
          const y = r * (size + gap)
          if (!cell) {
            return (
              <rect
                key={i}
                x={x}
                y={y}
                width={size}
                height={size}
                rx={2}
                fill="#f1f5f9"
              />
            )
          }
          const fill = PIE_COLORS[cell.catIdx % PIE_COLORS.length]
          const dim = activeValue && activeValue !== cell.label
          return (
            <rect
              key={i}
              x={x}
              y={y}
              width={size}
              height={size}
              rx={2}
              fill={fill}
              opacity={dim ? 0.3 : 1}
              style={{ cursor: 'pointer' }}
              onClick={() => onValueClick(cell.label)}
            >
              <title>
                {`${cell.label}: ${cell.count} rows (${(
                  (cell.count / total) *
                  100
                ).toFixed(1)}%)`}
              </title>
            </rect>
          )
        })}
      </svg>
    </div>
  )
}

// --- Cumulative coverage (multi-label only) ----------------------------
//
// Sorted-rank line of cumulative % of label occurrences. Steep early
// slope → distribution is concentrated in a few labels; flat tail →
// long-tail distribution. Helps decide whether to invest more in
// promoting tail labels into first-class metrics.
function CategoricalCoverageChart({
  valueCounts,
  totalCategorical,
}: CategoricalChartProps) {
  const total = totalCategorical || 1
  let running = 0
  const data = valueCounts.map((vc, i) => {
    running += vc.count
    return {
      rank: i + 1,
      label: vc.label,
      cumulative: (running / total) * 100,
      count: vc.count,
    }
  })
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: -8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis
          dataKey="rank"
          tick={{ fontSize: 10, fill: '#64748b' }}
          axisLine={{ stroke: '#e2e8f0' }}
          tickLine={false}
          label={{
            value: 'Label rank',
            position: 'insideBottomRight',
            offset: -2,
            fontSize: 10,
            fill: '#64748b',
          }}
        />
        <YAxis
          tick={{ fontSize: 10, fill: '#64748b' }}
          axisLine={false}
          tickLine={false}
          domain={[0, 100]}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip
          contentStyle={CHART_TOOLTIP_STYLE}
          labelStyle={CHART_TOOLTIP_LABEL_STYLE}
          itemStyle={CHART_TOOLTIP_ITEM_STYLE}
          formatter={(value: any, _name: any, payload: any) => [
            `${Number(value).toFixed(1)}% cumulative`,
            payload?.payload?.label ?? '—',
          ]}
          labelFormatter={(rank) => `Top ${rank}`}
        />
        <Line
          type="monotone"
          dataKey="cumulative"
          stroke="#6366f1"
          strokeWidth={2}
          dot={{ r: 3, fill: '#6366f1' }}
          isAnimationActive
          animationDuration={400}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

// --- Co-occurrence heatmap (multi-label only) --------------------------
//
// Reads ``metric.co_occurrence`` (label_a, label_b, count) emitted
// by the backend aggregator. Each cell encodes how often a pair of
// labels fired together on the same row. Falls back to an empty
// state when the field isn't populated yet (older payloads / rolling
// deploys / single-label metrics).
function CategoricalHeatmapChart({
  metric,
  valueCounts,
  onValueClick,
}: CategoricalChartProps) {
  const co = metric.co_occurrence
  const labels = valueCounts.map((v) => v.label)
  const labelIndex = new Map(labels.map((l, i) => [l, i]))
  const grid: number[][] = labels.map((_, i) =>
    labels.map((_, j) => (i === j ? valueCounts[i].count : 0)),
  )
  if (Array.isArray(co)) {
    for (const row of co) {
      const ai = labelIndex.get(row.a)
      const bi = labelIndex.get(row.b)
      if (ai == null || bi == null) continue
      grid[ai][bi] = row.count
      grid[bi][ai] = row.count
    }
  }
  let max = 0
  for (const row of grid) {
    for (const v of row) max = Math.max(max, v)
  }
  if (!Array.isArray(co) || max === 0) {
    return (
      <div className="rounded-md border border-dashed border-gray-200 bg-gray-50/50 px-4 py-6 text-center text-xs text-gray-500">
        Co-occurrence data isn't available for this metric yet — switch
        to another chart type or re-run the evaluation aggregate.
      </div>
    )
  }
  const cell = 22
  const gap = 2
  const labelW = 130
  const w = labelW + labels.length * (cell + gap)
  const h = labelW + labels.length * (cell + gap)
  return (
    <div className="overflow-auto py-1">
      <svg width={w} height={h} role="img" aria-label="Co-occurrence heatmap">
        {labels.map((lbl, i) => (
          <text
            key={`row-${i}`}
            x={labelW - 6}
            y={labelW + i * (cell + gap) + cell / 2 + 4}
            textAnchor="end"
            fontSize={10}
            fill="#334155"
          >
            <title>{lbl}</title>
            {truncateLabel(lbl, 18)}
          </text>
        ))}
        {labels.map((lbl, j) => (
          <text
            key={`col-${j}`}
            x={labelW + j * (cell + gap) + cell / 2}
            y={labelW - 6}
            transform={`rotate(-45 ${labelW + j * (cell + gap) + cell / 2} ${labelW - 6})`}
            textAnchor="start"
            fontSize={10}
            fill="#334155"
          >
            <title>{lbl}</title>
            {truncateLabel(lbl, 18)}
          </text>
        ))}
        {grid.map((row, i) =>
          row.map((v, j) => {
            const t = max > 0 ? v / max : 0
            const fill =
              v === 0
                ? '#f8fafc'
                : `rgba(99, 102, 241, ${0.15 + 0.85 * t})`
            return (
              <rect
                key={`${i}-${j}`}
                x={labelW + j * (cell + gap)}
                y={labelW + i * (cell + gap)}
                width={cell}
                height={cell}
                rx={3}
                fill={fill}
                style={{ cursor: i === j ? 'pointer' : 'default' }}
                onClick={() => {
                  if (i === j) onValueClick(labels[i])
                }}
              >
                <title>
                  {i === j
                    ? `${labels[i]}: ${v}`
                    : `${labels[i]} ∩ ${labels[j]}: ${v}`}
                </title>
              </rect>
            )
          }),
        )}
      </svg>
    </div>
  )
}
