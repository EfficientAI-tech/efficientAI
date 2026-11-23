import type { ReactNode } from 'react'
import {
  Area,
  AreaChart,
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
import { formatUsageCostExactUsd, type UsageDisplayCurrency } from '../../../lib/usageCurrency'
import type { ChartModel, ChartSeries } from './resultsDashboardSeries'
import { formatChartNumber, formatDayLabel } from './resultsDashboardSeries'
import type { ResultsChartType } from './resultsDashboardLayout'

const PRIMARY = '#ca8a04'
const GRID = '#e5e7eb'

type HeadlineProps = Pick<ChartModel, 'headline' | 'caption' | 'headlineRight' | 'captionRight'>

export function ChartHeadlineRow({
  headline,
  caption,
  headlineRight,
  captionRight,
  compact,
}: HeadlineProps & { compact?: boolean }) {
  if (!headline && !headlineRight) return null
  const valueClass = compact
    ? 'text-2xl font-semibold tracking-tight text-gray-900'
    : 'text-2xl font-semibold tracking-tight text-gray-900'
  const capClass = compact ? 'mt-0.5 text-xs text-gray-500' : 'mt-1 text-sm text-gray-500'
  if (headlineRight) {
    return (
      <div className="flex w-full max-w-full items-end">
        <div className="min-w-0">
          {headline ? <p className={valueClass}>{headline}</p> : null}
          {caption ? <p className={capClass}>{caption}</p> : null}
        </div>
        <div className="ml-auto shrink-0 pl-10 text-right sm:pl-12">
          {headlineRight ? <p className={valueClass}>{headlineRight}</p> : null}
          {captionRight ? <p className={capClass}>{captionRight}</p> : null}
        </div>
      </div>
    )
  }
  return (
    <>
      {headline ? <p className={valueClass}>{headline}</p> : null}
      {caption ? <p className={capClass}>{caption}</p> : null}
    </>
  )
}

function categoryKey(data: ChartModel['data']): 'name' | 'day' {
  return data[0] && 'name' in data[0] ? 'name' : 'day'
}

function chartDataWithLabels(data: ChartModel['data'], key: 'name' | 'day') {
  if (key !== 'day') return data
  return data.map((row) => ({
    ...row,
    day: typeof row.day === 'string' ? formatDayLabel(row.day) : row.day,
  }))
}

function formatTooltipValue(
  value: number | string | undefined,
  valueFormat: 'currency' | 'number',
  inrRate: number,
  displayCurrency: UsageDisplayCurrency,
): ReactNode {
  const num = typeof value === 'number' ? value : Number(value)
  if (valueFormat === 'currency' && Number.isFinite(num)) {
    return (
      <span className="tabular-nums">{formatUsageCostExactUsd(num, displayCurrency, inrRate)}</span>
    )
  }
  if (typeof value === 'number') return formatChartNumber(value)
  return value ?? '—'
}

function DrillTooltip({
  active,
  payload,
  label,
  drillable,
  valueFormat = 'number',
  inrRate = 95,
  displayCurrency = 'USD',
}: {
  active?: boolean
  payload?: Array<{ name?: string | number; value?: number | string; color?: string }>
  label?: string | number
  drillable?: boolean
  valueFormat?: 'currency' | 'number'
  inrRate?: number
  displayCurrency?: UsageDisplayCurrency
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-semibold text-gray-900">{label}</p>
      {payload.map((item) => {
        return (
          <p key={String(item.name)} className="font-medium" style={{ color: item.color ?? '#374151' }}>
            {item.name != null ? String(item.name) : 'Spend'}:{' '}
            {formatTooltipValue(item.value, valueFormat, inrRate, displayCurrency)}
          </p>
        )
      })}
      {drillable && (
        <p className="mt-1.5 border-t border-gray-100 pt-1.5 text-[10px] font-semibold text-primary-800">
          Click to drill in
        </p>
      )}
    </div>
  )
}

const INTERACTIVE_CHART_CLASS =
  'cursor-pointer [&_.recharts-surface]:cursor-pointer [&_.recharts-bar-rectangle]:cursor-pointer [&_.recharts-active-shape]:cursor-pointer'

function barInteractionProps(onCategory?: (label: string) => void) {
  if (!onCategory) return {}
  return {
    style: { cursor: 'pointer' } as const,
    activeBar: { fillOpacity: 0.72 },
  }
}

export function DrillChartPanel({
  model,
  display,
  height = 280,
  className = '',
  onCategory,
  onSeriesPoint,
  valueFormat = 'number',
  inrRate = 95,
  displayCurrency = 'USD',
}: {
  model: Pick<ChartModel, 'headline' | 'caption' | 'headlineRight' | 'captionRight' | 'data' | 'series' | 'horizontal' | 'stacked'>
  display?: ResultsChartType
  height?: number
  className?: string
  onCategory?: (label: string) => void
  /** Line/area multi-series: agent (series key) + optional calendar day. */
  onSeriesPoint?: (point: { series: string; sortKey?: string; dayLabel: string }) => void
  /** Pre-prod usage charts pass USD amounts from dashboard-ops. */
  valueFormat?: 'currency' | 'number'
  inrRate?: number
  displayCurrency?: UsageDisplayCurrency
}) {
  const { headline, caption, headlineRight, captionRight, series } = model
  const currencyAxis = valueFormat === 'currency'
    ? {
      width: 72,
      tickFormatter: (value: number) => formatUsageCostExactUsd(value, displayCurrency, inrRate),
    }
    : { width: 40, tickFormatter: undefined }
  const valueAxis = (
    <YAxis
      tick={{ fontSize: 11, fill: '#6b7280' }}
      axisLine={false}
      tickLine={false}
      width={currencyAxis.width}
      tickFormatter={currencyAxis.tickFormatter}
    />
  )
  const catKey = categoryKey(model.data)
  const data = chartDataWithLabels(model.data, catKey)
  const resolvedDisplay: ResultsChartType = display
    ?? (catKey === 'day' ? 'line' : model.horizontal ? 'bar' : 'bar')

  if (!data.length) {
    return (
      <div className={`rounded-xl border border-gray-200 bg-white p-5 shadow-sm ${className}`}>
        <ChartHeadlineRow
          headline={headline}
          caption={caption}
          headlineRight={headlineRight}
          captionRight={captionRight}
        />
        <p className="mt-6 text-sm text-gray-400">No data in this window.</p>
      </div>
    )
  }

  const drillable = Boolean(onCategory || onSeriesPoint)
  const grid = <CartesianGrid stroke={GRID} vertical={false} />
  const tooltip = (
    <Tooltip
      content={
        <DrillTooltip
          drillable={drillable}
          valueFormat={valueFormat}
          inrRate={inrRate}
          displayCurrency={displayCurrency}
        />
      }
      cursor={drillable ? { fill: '#fef9c3', radius: 4 } : { fill: '#f9fafb' }}
    />
  )
  const barProps = barInteractionProps(onCategory)

  const chartBody = (() => {
    if (model.stacked) {
      return (
        <ResponsiveContainer width="100%" height={height}>
          <BarChart layout="vertical" data={data} margin={{ top: 4, right: 16, left: 4, bottom: 4 }}>
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="name" width={124} tick={{ fontSize: 11, fill: '#4b5563' }} />
            {tooltip}
            {series.map((item) => (
              <Bar
                key={item.key}
                dataKey={item.key}
                stackId={item.stack ?? 'stack'}
                fill={item.color}
                barSize={20}
                {...barProps}
                onClick={(state) => {
                  const payload = (state as { payload?: { name?: string } })?.payload
                  const name = payload?.name ?? (state as { name?: string })?.name
                  if (name && onCategory) onCategory(name)
                }}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )
    }

    if (model.horizontal || (catKey === 'name' && resolvedDisplay === 'bar')) {
      const barHeight = Math.min(height, Math.max(160, data.length * 36))
      return (
        <ResponsiveContainer width="100%" height={barHeight}>
          <BarChart layout="vertical" data={data} margin={{ top: 4, right: 16, left: 4, bottom: 4 }}>
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="name" width={128} tick={{ fontSize: 11, fill: '#4b5563' }} />
            {tooltip}
            {series.map((item) => (
              <Bar
                key={item.key}
                dataKey={item.key}
                name={item.key}
                fill={item.color}
                barSize={22}
                radius={[0, 4, 4, 0]}
                {...barProps}
                onClick={(state) => {
                  const payload = (state as { payload?: { name?: string } })?.payload
                  const name = payload?.name ?? (state as { name?: string })?.name
                  if (name && onCategory) onCategory(name)
                }}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )
    }

    const chartClick = onCategory
      ? (state: { activeLabel?: string | number }) => {
        if (state?.activeLabel == null) return
        onCategory(String(state.activeLabel))
      }
      : undefined
    const chartStyle = drillable ? { cursor: 'pointer' as const } : undefined

    if (resolvedDisplay === 'area') {
      return (
        <ResponsiveContainer width="100%" height={height}>
          <AreaChart data={data} onClick={chartClick} style={chartStyle}>
            {grid}
            <XAxis dataKey={catKey} tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
            {valueAxis}
            {tooltip}
            {series.map((item) => (
              <Area
                key={item.key}
                type="monotone"
                dataKey={item.key}
                stroke={item.color}
                fill={item.color}
                fillOpacity={0.12}
                strokeWidth={1.75}
                dot={onSeriesPoint ? { r: 3, strokeWidth: 1, fill: item.color } : false}
                activeDot={
                  onSeriesPoint
                    ? {
                      r: 5,
                      onClick: (_event, dot) => {
                        const payload = (dot as { payload?: Record<string, unknown> })?.payload
                        if (!payload) return
                        onSeriesPoint({
                          series: item.key,
                          sortKey: typeof payload.sortKey === 'string' ? payload.sortKey : undefined,
                          dayLabel: String(payload.day ?? ''),
                        })
                      },
                    }
                    : undefined
                }
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      )
    }

    if (resolvedDisplay === 'line' || catKey === 'day') {
      return (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={data} onClick={chartClick} style={chartStyle}>
            {grid}
            <XAxis dataKey={catKey} tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
            {valueAxis}
            {tooltip}
            {series.map((item) => (
              <Line
                key={item.key}
                type="monotone"
                dataKey={item.key}
                stroke={item.color}
                strokeWidth={1.75}
                dot={onSeriesPoint ? { r: 3, strokeWidth: 1, fill: item.color } : false}
                activeDot={
                  onSeriesPoint
                    ? {
                      r: 5,
                      onClick: (_event, dot) => {
                        const payload = (dot as { payload?: Record<string, unknown> })?.payload
                        if (!payload) return
                        onSeriesPoint({
                          series: item.key,
                          sortKey: typeof payload.sortKey === 'string' ? payload.sortKey : undefined,
                          dayLabel: String(payload.day ?? ''),
                        })
                      },
                    }
                    : undefined
                }
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )
    }

    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} onClick={chartClick} style={chartStyle}>
          {grid}
          <XAxis dataKey={catKey} tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
          {valueAxis}
          {tooltip}
          {series.map((item) => (
            <Bar
              key={item.key}
              dataKey={item.key}
              fill={item.color}
              radius={[3, 3, 0, 0]}
              maxBarSize={32}
              {...barProps}
              onClick={(state) => {
                const payload = (state as { name?: string })?.name
                if (payload && onCategory) onCategory(payload)
              }}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    )
  })()

  return (
    <section className={`rounded-xl border border-gray-200 bg-white p-5 shadow-sm ${className}`}>
      <ChartHeadlineRow
        headline={headline}
        caption={caption}
        headlineRight={headlineRight}
        captionRight={captionRight}
      />
      <div
        className={`mt-4 min-h-[160px] [&_.recharts-surface]:outline-none ${drillable ? INTERACTIVE_CHART_CLASS : ''}`}
      >
        {chartBody}
      </div>
      {drillable && (
        <p className="mt-2 flex items-center gap-1.5 text-[11px] font-medium text-primary-800/90">
          <span className="inline-block h-3.5 w-3.5 rounded-sm border border-primary-300 bg-primary-50" aria-hidden />
          {catKey === 'day' && onSeriesPoint
            ? 'Click a point on the line to see runs with tool calls for that agent and day'
            : 'Click a bar or point to drill in'}
        </p>
      )}
    </section>
  )
}

export function DrillTrendChart({
  points,
  note,
  series = [{ key: 'value', color: PRIMARY }],
}: {
  points: Array<{ day: string; value: number }>
  note?: string
  series?: ChartSeries[]
}) {
  return (
    <DrillChartPanel
      model={{
        headline: points.length ? formatChartNumber(points[points.length - 1]?.value) : '—',
        caption: note,
        data: points,
        series,
        horizontal: false,
      }}
      display="line"
      height={240}
    />
  )
}