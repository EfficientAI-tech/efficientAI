import { useMemo, type ReactNode } from 'react'
import { Filter } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { CallImportMetricAggregate, MetricPeriodDelta } from '../../../../types/api'
import {
  CategoricalChart,
  CategoricalChartPicker,
  CategoryLegend,
  CHART_TOOLTIP_ITEM_STYLE,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_STYLE,
  sortValueCounts,
} from './CategoricalCharts'
import type { CategoricalChartType } from './chartPrefs'

function clampProseToSentences(
  text: string,
  maxSentences = 3,
  maxChars = 300,
): string {
  const trimmed = text.trim().replace(/\s*\n+\s*/g, ' ')
  if (!trimmed) return trimmed
  const sentences = trimmed.split(/(?<=[.!?])\s+/).filter(Boolean)
  let result = (sentences.length ? sentences.slice(0, maxSentences) : [trimmed])
    .join(' ')
    .trim()
  if (result.length > maxChars) {
    const cut = result.slice(0, maxChars - 3).replace(/\s+\S*$/, '')
    result = `${cut || result.slice(0, maxChars)}...`
  }
  return result
}

export default function MetricVisualization({
  metric,
  chartType,
  chartOverridden,
  onChangeChartType,
  isActive,
  activeValue,
  businessInsight,
  periodDelta,
  failurePoliciesSource,
  onValueClick,
}: {
  metric: CallImportMetricAggregate
  chartType: CategoricalChartType
  chartOverridden: boolean
  onChangeChartType: (type: CategoricalChartType | null) => void
  isActive: boolean
  activeValue: string | null
  businessInsight?: string | null
  periodDelta?: MetricPeriodDelta | null
  failurePoliciesSource?: 'inferred' | 'user' | null
  onValueClick: (value: string) => void
}) {
  const histogram = metric.histogram_buckets
  const valueCounts = useMemo(
    () => sortValueCounts(metric.value_counts),
    [metric.value_counts],
  )
  const hasNumeric = histogram.length > 0 || metric.mean != null
  const hasCategorical = valueCounts.length > 0
  const totalCategorical = valueCounts.reduce((sum, v) => sum + v.count, 0)
  const isMultiLabelParent = metric.is_multi_label_parent === true

  let chart: ReactNode = null
  if (histogram.length > 0) {
    const data = histogram.map((b) => ({
      label: `${b.x0.toFixed(2)}-${b.x1.toFixed(2)}`,
      count: b.count,
    }))
    chart = (
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
          <defs>
            <linearGradient id={`bar-num-${metric.metric_id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6366f1" stopOpacity={0.95} />
              <stop offset="100%" stopColor="#6366f1" stopOpacity={0.55} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fill: '#64748b' }}
            axisLine={{ stroke: '#e2e8f0' }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 10, fill: '#64748b' }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={CHART_TOOLTIP_STYLE}
            labelStyle={CHART_TOOLTIP_LABEL_STYLE}
            itemStyle={CHART_TOOLTIP_ITEM_STYLE}
            cursor={{ fill: 'rgba(99,102,241,0.08)' }}
            formatter={(value: any) => [`${value} rows`, 'Count']}
          />
          <Bar
            dataKey="count"
            fill={`url(#bar-num-${metric.metric_id})`}
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    )
  } else if (valueCounts.length) {
    chart = (
      <CategoricalChart
        metric={metric}
        chartType={chartType}
        valueCounts={valueCounts}
        totalCategorical={totalCategorical}
        activeValue={activeValue}
        onValueClick={onValueClick}
      />
    )
  }

  return (
    <div
      className={`group relative rounded-xl border bg-white p-4 transition-shadow ${
        isActive
          ? 'border-primary-300 ring-2 ring-primary-100 shadow-sm'
          : 'border-gray-200 hover:shadow-md hover:border-gray-300'
      }`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <p
            className="text-sm font-semibold text-gray-900 truncate"
            title={metric.metric_name}
          >
            {metric.metric_name}
          </p>
          <div className="mt-1 flex items-center gap-1.5 flex-wrap">
            <span
              className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-700"
              title={
                isMultiLabelParent
                  ? 'Rows scored. Each row may contribute to several labels.'
                  : 'Number of rows that produced a score for this metric.'
              }
            >
              n = {metric.count}
              {isMultiLabelParent ? ' rows' : ''}
            </span>
            {metric.skipped_count > 0 && (
              <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-50 text-amber-700">
                {metric.skipped_count} skipped
              </span>
            )}
            {metric.error_count > 0 && (
              <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-red-50 text-red-700">
                {metric.error_count} errors
              </span>
            )}
            {isMultiLabelParent ? (
              <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary-50 text-primary-700">
                Multi-label
              </span>
            ) : (
              metric.metric_type && (
                <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary-50 text-primary-700 capitalize">
                  {metric.metric_type}
                </span>
              )
            )}
            {periodDelta?.label ? (
              <span
                className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-700"
                title={periodDelta.detail || 'vs prior evaluation run'}
              >
                {periodDelta.label} vs prior
              </span>
            ) : null}
            {failurePoliciesSource === 'inferred' ? (
              <span
                className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-50 text-amber-800"
                title="Confirm failure values in Failure diagnostics → Generate clusters"
              >
                Suggested failure rate
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isActive && (
            <span className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary-100 text-primary-800">
              <Filter className="h-3 w-3" />
              Filtering
            </span>
          )}
          {hasCategorical && !hasNumeric && (
            <CategoricalChartPicker
              metric={metric}
              active={chartType}
              overridden={chartOverridden}
              onChange={onChangeChartType}
            />
          )}
        </div>
      </div>

      {periodDelta?.why ? (
        <p className="mb-3 text-[11px] text-slate-600 leading-snug">
          {clampProseToSentences(periodDelta.why, 2)}
        </p>
      ) : null}

      {hasNumeric && (
        <div className="mb-3 grid grid-cols-4 gap-2">
          {[
            {
              label: 'Mean',
              value: metric.mean,
              title: 'Average score across all rows',
              tone: 'neutral' as const,
            },
            {
              label: 'Best',
              value: metric.max,
              title: 'Highest single-row score',
              tone: 'good' as const,
            },
            {
              label: 'Worst',
              value: metric.min,
              title: 'Lowest single-row score',
              tone: 'bad' as const,
            },
            {
              label: 'σ',
              value: metric.stddev,
              title:
                'Standard deviation — lower means more consistent scoring',
              tone: 'neutral' as const,
            },
          ].map((stat) => (
            <div
              key={stat.label}
              title={stat.title}
              className="rounded-md bg-gradient-to-br from-gray-50 to-gray-100/60 border border-gray-100 px-2 py-1.5 text-center"
            >
              <p className="text-[9px] uppercase tracking-wider text-gray-500">
                {stat.label}
              </p>
              <p
                className={`text-xs font-semibold tabular-nums ${
                  stat.tone === 'good'
                    ? 'text-emerald-700'
                    : stat.tone === 'bad'
                      ? 'text-rose-700'
                      : 'text-gray-900'
                }`}
              >
                {stat.value != null ? stat.value.toFixed(2) : '—'}
              </p>
            </div>
          ))}
        </div>
      )}

      {chart ?? (
        <p className="text-xs text-gray-400 italic py-8 text-center">
          No values recorded yet.
        </p>
      )}

      {businessInsight && (
        <div className="mt-3 rounded-lg border border-primary-100 bg-primary-50/60 px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-primary-700">
            Business insight
          </p>
          <p className="mt-1 text-xs leading-relaxed text-gray-700">
            {businessInsight}
          </p>
        </div>
      )}

      {hasCategorical && totalCategorical > 0 && (
        <CategoryLegend
          valueCounts={valueCounts}
          totalCategorical={totalCategorical}
          activeValue={activeValue}
          onValueClick={onValueClick}
        />
      )}
    </div>
  )
}
