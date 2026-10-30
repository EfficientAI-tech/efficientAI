import { createContext, useContext, useState, type ReactNode } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import DistributionChart from './charts/DistributionChart'
import HorizontalStackedBar from './charts/HorizontalStackedBar'
import InsightTrendChart from './charts/InsightTrendChart'
import { agentChartSeries, CHART_PALETTE, TOP_BAR_COLOR, WIDGET_COLORS } from './dashboardSection'
import {
  callsByAgent,
  callsOverTimeByAgent,
  costSummary,
  dailySeries,
  distinctIntegrationsUsed,
  durationByDayByAgent,
  durationStats,
  failureOverTime,
  failureSummary,
  integrationUsageOverTimeMulti,
  integrationUsageRows,
  metricUsageOverTime,
  metricUsageRows,
  outcomeNotAchieved,
  scenarioStats,
  toolCallTotal,
  toolsOnCall,
} from './dashboardSelectors'
import type { WidgetDisplay, WidgetType } from './dashboardLayout'
import { useDashboardNav } from './dashboardNav'
import { formatDuration, formatGlobalValue, globalMetricById } from './globalMetrics'
import { formatDelta, percentDelta } from './insightFormat'
import { MOCK_AGENTS, MOCK_METRICS, SCENARIOS } from './mockCatalog'
import { formatMoney } from './mockUsage'
import type { MockCall } from './mockCalls'

const RAIL_METRIC: Partial<Record<WidgetType, string>> = {
  closing_quality: 'closing_quality',
  early_ending: 'early_ending',
  talk_ratio: 'talk_ratio',
  rag_failures: 'rag_call_failures',
  silence_duration: 'silence_duration',
  longest_pause: 'longest_pause',
}

const WidgetAgentContext = createContext<string | null>(null)

function useWidgetNav() {
  const nav = useDashboardNav()
  const agentId = useContext(WidgetAgentContext)
  if (!agentId) return nav
  return {
    ...nav,
    calls: nav.calls.filter((call) => call.agentId === agentId),
    previousCalls: nav.previousCalls.filter((call) => call.agentId === agentId),
  }
}

export default function WidgetBody({
  type,
  display,
  compact,
  details,
  agentId,
}: {
  type: WidgetType
  display: WidgetDisplay
  compact?: 'top' | 'rail'
  details?: boolean
  agentId?: string | null
}) {
  const asChart = display !== 'number'
  const color = compact === 'top' ? TOP_BAR_COLOR : WIDGET_COLORS[type] ?? CHART_PALETTE[0]
  const height = compact === 'rail' ? 56 : compact === 'top' ? 72 : 180

  const body =
    type === 'cost' ? (
      <CostBody compact={compact} asChart={asChart} display={display} color={color} height={height} />
    ) : type === 'tool_calls' ? (
      <ToolCallsBody compact={compact} asChart={asChart} display={display} color={color} height={height} />
    ) : type === 'tool_use' ? (
      <ToolsBody compact={compact} asChart={asChart} display={display} color={color} height={height} />
    ) : type === 'failures' ? (
      <FailuresBody compact={compact} asChart={asChart} display={display} color={color} height={height} />
    ) : type === 'total_calls' ? (
      <TotalCallsBody asChart={asChart} compact={compact} details={details} display={display} color={color} height={height} />
    ) : type === 'avg_duration' ? (
      <DurationBody asChart={asChart} compact={compact} details={details} display={display} color={color} height={height} />
    ) : type === 'metric_usage' ? (
      <MetricUsageBody display={display} height={height} />
    ) : type === 'scenarios' ? (
      <ScenariosBody details={details} display={display} height={height} />
    ) : null

  if (body) {
    return <WidgetAgentContext.Provider value={agentId ?? null}>{body}</WidgetAgentContext.Provider>
  }

  const metricId = RAIL_METRIC[type]
  if (metricId) {
    return (
      <WidgetAgentContext.Provider value={agentId ?? null}>
        <RailMetricBody
          type={type}
          metricId={metricId}
          display={display}
          compact={compact}
          asChart={asChart}
          color={color}
          height={height}
        />
      </WidgetAgentContext.Provider>
    )
  }
  return null
}

function CostBody({
  compact,
  asChart,
  display,
  color,
  height,
}: {
  compact?: 'top' | 'rail'
  asChart: boolean
  display: WidgetDisplay
  color: string
  height: number
}) {
  const nav = useWidgetNav()
  const summary = costSummary(nav.calls)
  const previous = costSummary(nav.previousCalls)
  const points = summary.byDay.map((row) => ({ label: row.day.slice(5), value: row.value }))
  const kpi = {
    value: formatMoney(summary.totalUsd, nav.currency),
    delta: percentDelta(summary.totalUsd, previous.totalUsd),
    compact,
    onClick: () => nav.openUsage(),
  }
  if (!asChart) return <KpiBlock {...kpi} spark={points} color={color} />
  return (
    <ChartFrame {...kpi} color={color}>
      <InsightTrendChart points={points} kind={chartKind(display)} color={color} height={height} />
    </ChartFrame>
  )
}

function ToolCallsBody({
  compact,
  asChart,
  display,
  color,
  height,
}: {
  compact?: 'top' | 'rail'
  asChart: boolean
  display: WidgetDisplay
  color: string
  height: number
}) {
  const nav = useWidgetNav()
  const current = toolCallTotal(nav.calls)
  const previous = toolCallTotal(nav.previousCalls)
  const trend = dailySeries(nav.calls, (call) => toolsOnCall(call).length).map((row) => ({
    label: row.day.slice(5),
    value: row.value,
  }))
  const kpi = {
    value: current.toLocaleString(),
    delta: percentDelta(current, previous),
    compact,
    onClick: () => nav.openToolCalls(),
  }
  if (!asChart) return <KpiBlock {...kpi} spark={trend} color={color} />
  return (
    <ChartFrame {...kpi} color={color}>
      <InsightTrendChart points={trend} kind={chartKind(display)} color={color} height={height} />
    </ChartFrame>
  )
}

function ToolsBody({
  compact,
  asChart,
  display,
  color,
  height,
}: {
  compact?: 'top' | 'rail'
  asChart: boolean
  display: WidgetDisplay
  color: string
  height: number
}) {
  const nav = useWidgetNav()
  const rows = integrationUsageRows(nav.calls).filter((row) => row.count > 0)
  const current = distinctIntegrationsUsed(nav.calls)
  const previous = distinctIntegrationsUsed(nav.previousCalls)
  const ids = rows.map((row) => row.id ?? row.name)
  const trend = integrationUsageOverTimeMulti(nav.calls, ids).map((row) => ({
    label: String(row.day).slice(5),
    ...row,
  }))
  const stacked = rows.map((row) => {
    const point: Record<string, string | number> = { name: row.name }
    for (const agent of row.byAgent) point[agent.agentId] = agent.count
    return point
  })

  const kpi = {
    value: String(current),
    delta: percentDelta(current, previous),
    compact,
    onClick: () => nav.openTools(),
  }
  if (!asChart) return <KpiBlock {...kpi} spark={trend} color={color} />
  const chart =
    display === 'donut' ? (
      <DonutBlock
        rows={rows.map((row) => ({ id: row.id ?? row.name, name: row.name, count: row.count, color: row.color }))}
        total={current}
        height={height}
        hideTotal
        onSelect={(id) => nav.openTool(id)}
      />
    ) : display === 'stacked' || display === 'bar' ? (
      <HorizontalStackedBar rows={stacked} series={agentChartSeries()} onBarClick={(name) => nav.openTool(name)} height={height} />
    ) : (
      <InsightTrendChart
        points={trend}
        kind={chartKind(display)}
        color={color}
        height={height}
        series={rows.map((row) => ({
          key: row.id ?? row.name,
          label: row.name,
          color: row.color,
        }))}
      />
    )
  return <ChartFrame {...kpi} color={color}>{chart}</ChartFrame>
}

function FailuresBody({
  compact,
  asChart,
  display,
  color,
  height,
}: {
  compact?: 'top' | 'rail'
  asChart: boolean
  display: WidgetDisplay
  color: string
  height: number
}) {
  const nav = useWidgetNav()
  const current = failureSummary(nav.calls)
  const previous = failureSummary(nav.previousCalls)
  const trend = failureOverTime(nav.calls).map((row) => ({
    label: row.day.slice(5),
    tools: row.tools,
    outcomes: row.outcomes,
  }))
  const total = current.toolFailures + current.outcomesNotAchieved
  const previousTotal = previous.toolFailures + previous.outcomesNotAchieved
  const kpi = {
    value: total.toLocaleString(),
    delta: percentDelta(total, previousTotal),
    compact,
    onClick: () => nav.openFailures(),
  }
  if (!asChart) {
    return (
      <button type="button" onClick={() => nav.openFailures()} className="grid w-full grid-cols-2 gap-6 text-left">
        <KpiBlock
          value={current.toolFailures.toLocaleString()}
          delta={percentDelta(current.toolFailures, previous.toolFailures)}
          compact={compact}
          caption="Tool calls failed"
          size="split"
        />
        <KpiBlock
          value={current.outcomesNotAchieved.toLocaleString()}
          delta={percentDelta(current.outcomesNotAchieved, previous.outcomesNotAchieved)}
          compact={compact}
          caption="Outcomes not achieved"
          size="split"
        />
      </button>
    )
  }
  const rows = [
    { id: 'tool', name: 'Tool calls failed', count: current.toolFailures, color: '#e11d48' },
    { id: 'outcome', name: 'Outcomes not achieved', count: current.outcomesNotAchieved, color: '#ea580c' },
  ]
  const chart =
    display === 'donut' ? (
      <DonutBlock
        rows={rows}
        total={total}
        height={height}
        hideTotal
        onSelect={(id) => nav.openFailures(id === 'outcome' ? 'outcome' : 'tool')}
      />
    ) : (
      <InsightTrendChart
        points={trend}
        kind={chartKind(display) === 'bar' ? 'stacked' : chartKind(display)}
        height={height}
        color={color}
        series={[
          { key: 'tools', label: 'Tool failures', color: '#e11d48' },
          { key: 'outcomes', label: 'Outcomes missed', color: '#ea580c' },
        ]}
      />
    )
  return <ChartFrame {...kpi} color={color}>{chart}</ChartFrame>
}

function TotalCallsBody({
  asChart,
  compact,
  details,
  display,
  color,
  height,
}: {
  asChart: boolean
  compact?: 'top' | 'rail'
  details?: boolean
  display: WidgetDisplay
  color: string
  height: number
}) {
  const nav = useWidgetNav()
  const rows = callsByAgent(nav.calls)
  const trend = dailySeries(nav.calls, () => 1).map((row) => ({ label: row.day.slice(5), value: row.value }))
  const stacked = callsOverTimeByAgent(nav.calls).map((row) => ({
    label: String(row.day).slice(5),
    ...row,
  }))
  const kpi = {
    value: nav.calls.length.toLocaleString(),
    delta: percentDelta(nav.calls.length, nav.previousCalls.length),
    compact,
  }
  if (!asChart) return <KpiBlock {...kpi} spark={trend} color={color} />
  const chart =
    display === 'donut' ? (
      <DonutBlock
        rows={rows.map((row, index) => ({
          id: row.agentId,
          name: row.agentName,
          count: row.count,
          color: CHART_PALETTE[index % CHART_PALETTE.length],
        }))}
        total={nav.calls.length}
        height={height}
        hideTotal
        onSelect={(id) => nav.openAgent(id)}
      />
    ) : display === 'distribution' ? (
      <DistributionChart buckets={histogram(nav.calls.map((call) => call.durationSeconds))} />
    ) : (
      <InsightTrendChart
        points={display === 'stacked' ? stacked : trend}
        kind={chartKind(display)}
        color={color}
        height={height}
        series={display === 'stacked' ? agentChartSeries() : undefined}
      />
    )
  return (
    <ChartFrame {...kpi} color={color}>
      {chart}
      {details && display !== 'donut' && (
        <ul className="mt-3 space-y-1 text-sm text-gray-600">
          {rows.map((row) => (
            <li key={row.agentId}>
              <button type="button" className="hover:underline" onClick={() => nav.openAgent(row.agentId)}>
                {row.agentName} · {row.count.toLocaleString()}
              </button>
            </li>
          ))}
        </ul>
      )}
    </ChartFrame>
  )
}

function DurationBody({
  asChart,
  compact,
  details,
  display,
  color,
  height,
}: {
  asChart: boolean
  compact?: 'top' | 'rail'
  details?: boolean
  display: WidgetDisplay
  color: string
  height: number
}) {
  const nav = useWidgetNav()
  const stats = durationStats(nav.calls)
  const previous = durationStats(nav.previousCalls)
  const trend = dailyAverage(nav.calls, (call) => call.durationSeconds)
  const stacked = durationByDayByAgent(nav.calls).map((row) => ({
    label: String(row.day).slice(5),
    ...row,
  }))
  const kpi = {
    value: formatDuration(stats.avg),
    delta: percentDelta(stats.avg, previous.avg),
    compact,
    onClick: () => nav.openMetric('avg_duration'),
  }
  if (!asChart) return <KpiBlock {...kpi} spark={trend} color={color} />
  const buckets = histogram(nav.calls.map((call) => call.durationSeconds), display === 'donut' ? 4 : 6)
  const chart =
    display === 'distribution' ? (
      <DistributionChart buckets={buckets} />
    ) : display === 'donut' ? (
      <DonutBlock
        rows={buckets.map((bucket, index) => ({
          id: bucket.label ?? String(index),
          name: bucket.label ?? `${Math.round(bucket.x0)}–${Math.round(bucket.x1)}s`,
          count: bucket.count,
          color: CHART_PALETTE[index % CHART_PALETTE.length],
        }))}
        total={nav.calls.length}
        height={height}
        hideTotal
      />
    ) : (
      <InsightTrendChart
        points={display === 'stacked' ? stacked : trend}
        kind={chartKind(display)}
        color={color}
        height={height}
        series={display === 'stacked' ? agentChartSeries() : undefined}
      />
    )
  return (
    <ChartFrame {...kpi} color={color}>
      {chart}
      {details && (
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm text-gray-600">
          <Stat label="Longest" value={stats.longest ? formatDuration(stats.longest.durationSeconds) : '—'} onClick={() => stats.longest && nav.openCall(stats.longest.id)} />
          <Stat label="Shortest" value={stats.shortest ? formatDuration(stats.shortest.durationSeconds) : '—'} onClick={() => stats.shortest && nav.openCall(stats.shortest.id)} />
          <Stat label="Median" value={formatDuration(stats.median)} />
          <Stat label="Silence" value={formatDuration(stats.silenceAvg)} onClick={() => nav.openMetric('silence_duration')} />
          <Stat
            label="Longest pause"
            value={formatDuration(stats.longestPause)}
            onClick={() => stats.longestPauseCall && nav.openCall(stats.longestPauseCall.id)}
          />
        </dl>
      )}
    </ChartFrame>
  )
}

function MetricUsageBody({ display, height }: { display: WidgetDisplay; height: number }) {
  const nav = useWidgetNav()
  const color = WIDGET_COLORS.metric_usage
  const [sort, setSort] = useState<'most' | 'least'>('most')
  const [group, setGroup] = useState<'all' | 'global' | 'local'>('all')
  const [selected, setSelected] = useState<string[]>([])
  const rows = metricUsageRows(nav.calls)
    .filter((row) => (group === 'all' ? true : row.group === group))
    .sort((a, b) => (sort === 'most' ? b.count - a.count : a.count - b.count))
  const ids = selected.length ? selected : rows.slice(0, 4).map((row) => row.id)
  const series = metricUsageOverTime(nav.calls, ids).map((row) => ({
    label: String(row.day).slice(5),
    ...row,
  }))
  const names = new Map([
    ...MOCK_METRICS.map((metric) => [metric.id, metric.name] as const),
    ...rows.map((row) => [row.id, row.name] as const),
  ])
  const total = rows.filter((row) => ids.includes(row.id)).reduce((sum, row) => sum + row.count, 0)
  const previousTotal = metricUsageRows(nav.previousCalls)
    .filter((row) => ids.includes(row.id))
    .reduce((sum, row) => sum + row.count, 0)
  const kpi = { value: total.toLocaleString(), delta: percentDelta(total, previousTotal) }
  const chips = (
    <div className="mt-3 flex flex-wrap gap-1">
      {rows.map((row, index) => (
        <button
          key={row.id}
          type="button"
          onClick={() =>
            setSelected((current) =>
              current.includes(row.id) ? current.filter((id) => id !== row.id) : [...current, row.id],
            )
          }
          className={`rounded-full px-2 py-0.5 text-[11px] ${
            ids.includes(row.id) ? 'text-white' : 'bg-gray-100 text-gray-600'
          }`}
          style={ids.includes(row.id) ? { backgroundColor: CHART_PALETTE[index % CHART_PALETTE.length] } : undefined}
        >
          {row.name}
        </button>
      ))}
    </div>
  )
  if (display === 'donut') {
    return (
      <ChartFrame {...kpi} color={color}>
        <DonutBlock
          rows={rows.slice(0, 8).map((row, index) => ({
            id: row.id,
            name: row.name,
            count: row.count,
            color: CHART_PALETTE[index % CHART_PALETTE.length],
          }))}
          total={total}
          height={height}
          hideTotal
          onSelect={(id) => nav.openMetric(id)}
        />
        {chips}
      </ChartFrame>
    )
  }
  return (
    <ChartFrame {...kpi} color={color}>
      <div className="mb-3 flex flex-wrap gap-1">
        <MiniToggle value={sort} onChange={setSort} options={[['most', 'Most used'], ['least', 'Least used']]} />
        <MiniToggle value={group} onChange={setGroup} options={[['all', 'All'], ['global', 'Global'], ['local', 'Local']]} />
      </div>
      <InsightTrendChart
        points={series}
        kind={chartKind(display)}
        height={height}
        series={ids.map((id, index) => ({
          key: id,
          label: names.get(id) ?? id,
          color: CHART_PALETTE[index % CHART_PALETTE.length],
        }))}
      />
      {chips}
    </ChartFrame>
  )
}

function ScenariosBody({ details, display, height }: { details?: boolean; display: WidgetDisplay; height: number }) {
  const nav = useWidgetNav()
  const color = WIDGET_COLORS.scenarios
  const stats = scenarioStats(nav.calls)
  const scenarioNames = [...new Set(SCENARIOS.map((scenario) => scenario.name))]
  const rows = MOCK_AGENTS.map((agent) => {
    const row: Record<string, string | number> = { label: agent.name }
    const agentRow = stats.byAgent.find((item) => item.agentId === agent.id)
    for (const item of agentRow?.byScenario ?? []) row[item.name] = item.count
    return row
  })
  const previousTotal = scenarioStats(nav.previousCalls).total
  const kpi = { value: String(stats.total), delta: percentDelta(stats.total, previousTotal) }
  if (display === 'donut') {
    const counts = new Map<string, number>()
    for (const agentRow of stats.byAgent) {
      for (const item of agentRow.byScenario) counts.set(item.name, (counts.get(item.name) ?? 0) + item.count)
    }
    const donut = [...counts.entries()].map(([name, count], index) => ({
      id: name,
      name,
      count,
      color: CHART_PALETTE[index % CHART_PALETTE.length],
    }))
    return (
      <ChartFrame {...kpi} color={color}>
        <DonutBlock rows={donut} total={stats.total} height={height} hideTotal />
      </ChartFrame>
    )
  }
  return (
    <ChartFrame {...kpi} color={color}>
      <InsightTrendChart
        points={rows}
        kind={display === 'area' || display === 'line' ? display : 'stacked'}
        height={height}
        series={scenarioNames.map((name, index) => ({
          key: name,
          label: name,
          color: CHART_PALETTE[index % CHART_PALETTE.length],
        }))}
      />
      {details && (
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm text-gray-600">
          <Stat label="Scenarios run" value={String(stats.total)} />
          <Stat label="Most metrics" value={stats.richest[0] ? `${stats.richest[0].name} (${stats.richest[0].metricIds.length})` : '—'} />
          <Stat label="Most simulated" value={stats.mostFrequent[0]?.name ?? '—'} />
        </dl>
      )}
    </ChartFrame>
  )
}

function RailMetricBody({
  type,
  metricId,
  display,
  compact,
  asChart,
  color,
  height,
}: {
  type: WidgetType
  metricId: string
  display: WidgetDisplay
  compact?: 'top' | 'rail'
  asChart: boolean
  color: string
  height: number
}) {
  const nav = useWidgetNav()
  const def = globalMetricById(metricId)
  const values = nav.calls.map((call) => railValue(call, metricId))
  const prev = nav.previousCalls.map((call) => railValue(call, metricId))
  const avg = average(values)
  const prevAvg = average(prev)
  const trend = dailyAverage(nav.calls, (call) => railValue(call, metricId))
  const kpi = (
    <KpiBlock
      value={def ? formatGlobalValue(def, avg) : '—'}
      delta={avg != null && prevAvg != null ? percentDelta(avg, prevAvg) : null}
      compact={compact}
      onClick={() => nav.openMetric(metricId)}
    />
  )
  if (!asChart) {
    return (
      <div>
        {kpi}
        {compact === 'rail' && <InsightTrendChart points={trend} kind="line" color={color} height={48} />}
      </div>
    )
  }
  if (display === 'distribution') {
    return (
      <div>
        {kpi}
        <DistributionChart buckets={histogram(values)} />
      </div>
    )
  }
  if (display === 'donut' && type === 'talk_ratio') {
    const agentShare = Math.round((avg ?? 0) * 100)
    return (
      <div>
        {kpi}
        <DonutBlock
          rows={[
            { id: 'agent', name: 'Agent talk', count: agentShare, color: '#059669' },
            { id: 'customer', name: 'Customer talk', count: Math.max(0, 100 - agentShare), color: '#0891b2' },
          ]}
          total={100}
          height={Math.max(height, 96)}
          hideTotal
        />
      </div>
    )
  }
  if (display === 'donut') {
    const fails = nav.calls.filter((call) =>
      type === 'early_ending' ? call.computed.earlyEnding > 0 : type === 'rag_failures' ? call.computed.ragCallFailures > 0 : outcomeNotAchieved(call),
    ).length
    return (
      <div>
        {kpi}
        <DonutBlock
          rows={[
            { id: 'hit', name: def?.name ?? type, count: fails, color },
            { id: 'rest', name: 'Other calls', count: Math.max(0, nav.calls.length - fails), color: '#e5e7eb' },
          ]}
          total={nav.calls.length}
          height={Math.max(height, 96)}
          hideTotal
        />
      </div>
    )
  }
  return (
    <div>
      {kpi}
      <InsightTrendChart points={trend} kind={chartKind(display)} color={color} height={height} />
    </div>
  )
}

function ChartFrame({
  value,
  delta,
  compact,
  onClick,
  color,
  children,
}: {
  value: string
  delta: number | null
  compact?: 'top' | 'rail'
  onClick?: () => void
  color?: string
  children: ReactNode
}) {
  return (
    <div>
      <KpiBlock value={value} delta={delta} compact={compact} onClick={onClick} color={color} />
      {children}
    </div>
  )
}

function DonutBlock({
  rows,
  total,
  height,
  onSelect,
  hideTotal,
}: {
  rows: Array<{ id: string; name: string; count: number; color?: string }>
  total: number
  height: number
  onSelect?: (id: string) => void
  hideTotal?: boolean
}) {
  const chartHeight = Math.max(96, height)
  return (
    <div>
      <div className="flex items-center gap-3">
        {!hideTotal && <p className="text-3xl font-semibold tracking-tight text-gray-900">{total.toLocaleString()}</p>}
        <div className="flex-1" style={{ height: chartHeight }}>
          <ResponsiveContainer>
            <PieChart>
              <Pie data={rows} dataKey="count" nameKey="name" innerRadius={28} outerRadius={48}>
                {rows.map((row) => (
                  <Cell
                    key={row.id}
                    fill={row.color ?? CHART_PALETTE[0]}
                    cursor={onSelect ? 'pointer' : undefined}
                    onClick={() => onSelect?.(row.id)}
                  />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
      <ul className="mt-1 space-y-1 text-xs text-gray-600">
        {rows.map((row) => (
          <li key={row.id}>
            <button
              type="button"
              className="flex w-full items-center gap-1.5 hover:underline"
              onClick={() => onSelect?.(row.id)}
            >
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: row.color ?? CHART_PALETTE[0] }} />
              <span className="truncate">{row.name}</span>
              <span className="ml-auto tabular-nums text-gray-900">{row.count.toLocaleString()}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function KpiBlock({
  value,
  delta,
  compact,
  caption,
  onClick,
  size,
  spark,
  color,
}: {
  value: string
  delta: number | null
  compact?: 'top' | 'rail'
  caption?: string
  onClick?: () => void
  size?: 'split'
  spark?: Array<Record<string, string | number>>
  color?: string
}) {
  const formatted = formatDelta(delta)
  const numberClass =
    compact === 'rail' ? 'text-2xl' : size === 'split' ? 'text-3xl leading-none' : 'text-[42px] leading-none'
  const inner = (
    <>
      {caption && <p className="mb-2 text-xs text-gray-500">{caption}</p>}
      <p
        className={`font-semibold tabular-nums tracking-tight ${numberClass} ${compact === 'top' || compact === 'rail' ? 'text-gray-900' : ''}`}
        style={compact !== 'top' && compact !== 'rail' && color ? { color } : undefined}
      >
        {value}
      </p>
      {formatted && compact !== 'rail' && (
        <p className={`mt-2 mb-1 flex items-center gap-1 text-sm ${formatted.up ? 'text-emerald-600' : 'text-rose-600'}`}>
          <span aria-hidden>{formatted.up ? '↗' : '↘'}</span>
          {formatted.text}
        </p>
      )}
      {spark && compact !== 'rail' && (
        <InsightTrendChart points={spark} kind="line" color={color} height={44} quiet />
      )}
    </>
  )
  if (!onClick) return <div className={compact === 'rail' ? '' : 'pt-3'}>{inner}</div>
  return (
    <button type="button" onClick={onClick} className={`w-full text-left ${compact === 'rail' ? '' : 'pt-3'}`}>
      {inner}
    </button>
  )
}

function Stat({ label, value, onClick }: { label: string; value: string; onClick?: () => void }) {
  const inner = (
    <>
      <dt className="text-xs uppercase tracking-wide text-gray-400">{label}</dt>
      <dd className="mt-0.5 truncate font-medium text-gray-800">{value}</dd>
    </>
  )
  if (!onClick) return <div>{inner}</div>
  return (
    <button type="button" onClick={onClick} className="text-left hover:underline">
      {inner}
    </button>
  )
}

function MiniToggle<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T
  onChange: (value: T) => void
  options: Array<[T, string]>
}) {
  return (
    <div className="inline-flex rounded-md bg-gray-100 p-0.5">
      {options.map(([id, label]) => (
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${value === id ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'}`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function chartKind(display: WidgetDisplay): 'bar' | 'area' | 'line' | 'stacked' {
  if (display === 'area' || display === 'line' || display === 'stacked') return display
  return 'bar'
}

function average(values: number[]): number | null {
  if (values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function railValue(call: MockCall, metricId: string): number {
  if (metricId === 'closing_quality') return call.computed.closingQuality
  if (metricId === 'early_ending') return call.computed.earlyEnding
  if (metricId === 'talk_ratio') return call.computed.talkRatio ?? 0
  if (metricId === 'rag_call_failures') return call.computed.ragCallFailures
  if (metricId === 'silence_duration') return call.computed.silenceAvgSeconds
  return call.computed.silenceMaxSeconds
}

function dailyAverage(calls: MockCall[], read: (call: MockCall) => number): Array<{ label: string; value: number }> {
  const map = new Map<string, { sum: number; n: number }>()
  for (const call of calls) {
    const day = call.startedAt.slice(0, 10)
    const row = map.get(day) ?? { sum: 0, n: 0 }
    row.sum += read(call)
    row.n += 1
    map.set(day, row)
  }
  return [...map.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([day, row]) => ({ label: day.slice(5), value: row.n ? row.sum / row.n : 0 }))
}

function histogram(values: number[], buckets = 6): Array<{ x0: number; x1: number; count: number; label: string }> {
  if (values.length === 0) return []
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const size = span / buckets
  const counts = Array.from({ length: buckets }, (_, index) => ({
    x0: min + index * size,
    x1: min + (index + 1) * size,
    count: 0,
    label: '',
  }))
  for (const value of values) {
    const index = Math.min(buckets - 1, Math.floor((value - min) / size))
    counts[index].count += 1
  }
  return counts.map((bucket) => ({
    ...bucket,
    label: `${bucket.x0.toFixed(1)}–${bucket.x1.toFixed(1)}`,
  }))
}
