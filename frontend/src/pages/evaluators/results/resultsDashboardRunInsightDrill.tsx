import { useState, type ReactNode } from 'react'
import { ChevronDown, ListFilter } from 'lucide-react'
import type { EvaluatorResultRow } from '../../../types/api'
import { formatDuration } from './resultsDashboardSeries'

const PRIMARY = '#ca8a04'

export function RunInsightFilterBar({
  dayLabel,
  scenarioName,
  onClearDay,
  onClearScenario,
  onClearAll,
  embedded,
}: {
  dayLabel: string | null
  scenarioName: string | null
  onClearDay: () => void
  onClearScenario: () => void
  onClearAll: () => void
  embedded?: boolean
}) {
  if (!dayLabel && !scenarioName) {
    return (
      <div className="flex items-start gap-2 text-xs text-gray-600">
        <ListFilter className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden />
        <p>
          {embedded ? (
            <>
              Pick a <span className="font-medium text-gray-800">scenario</span> in the breakdown below — the{' '}
              <span className="font-medium text-gray-800">run list</span> at the bottom of this card updates live.
              You can also click a <span className="font-medium text-gray-800">day</span> on the trend chart above.
            </>
          ) : (
            <>
              Click a <span className="font-medium text-gray-700">day</span> on the trend chart, or a{' '}
              <span className="font-medium text-gray-700">scenario</span> below, to narrow the run list.
            </>
          )}
        </p>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
        <ListFilter className="h-3 w-3" aria-hidden />
        Active filters
      </span>
      {dayLabel && (
        <button
          type="button"
          onClick={onClearDay}
          className="inline-flex items-center gap-1 rounded-full border border-primary-200 bg-primary-50 px-2.5 py-0.5 text-xs font-medium text-primary-900 hover:bg-primary-100"
        >
          Day: {dayLabel}
          <span className="text-primary-600">×</span>
        </button>
      )}
      {scenarioName && (
        <button
          type="button"
          onClick={onClearScenario}
          className="inline-flex items-center gap-1 rounded-full border border-primary-200 bg-primary-50 px-2.5 py-0.5 text-xs font-medium text-primary-900 hover:bg-primary-100"
        >
          {scenarioName}
          <span className="text-primary-600">×</span>
        </button>
      )}
      {(dayLabel || scenarioName) && (
        <button type="button" onClick={onClearAll} className="text-xs font-medium text-gray-500 hover:text-gray-800">
          Clear all
        </button>
      )}
    </div>
  )
}

function BarRow({
  label,
  value,
  max,
  suffix,
  active,
  onClick,
}: {
  label: string
  value: number
  max: number
  suffix: string
  active?: boolean
  onClick?: () => void
}) {
  const width = max ? Math.round((value / max) * 100) : 0
  const body = (
    <>
      <span className="min-w-0 truncate text-sm text-gray-800">
        {label}
        {active ? (
          <span className="ml-2 inline-flex rounded bg-primary-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary-900">
            Filtering runs
          </span>
        ) : null}
      </span>
      <span className="col-span-2 h-2 overflow-hidden rounded-full bg-gray-100">
        <span className="block h-full rounded-full" style={{ width: `${width}%`, backgroundColor: PRIMARY }} />
      </span>
      <span className="text-right text-xs tabular-nums text-gray-500">{suffix}</span>
    </>
  )
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-pressed={active}
        className={`grid w-full grid-cols-[minmax(0,1fr)_minmax(0,2fr)_5rem] items-center gap-3 rounded-lg border border-transparent px-2 py-2 text-left transition-colors ${active
          ? 'border-primary-200 bg-primary-50/90 ring-1 ring-primary-200'
          : 'hover:border-gray-200 hover:bg-gray-50'
          }`}
      >
        {body}
      </button>
    )
  }
  return <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)_5rem] items-center gap-3 px-2 py-2">{body}</div>
}

function mergeScenarioCounts(
  rows: Array<{ name: string; count: number; failed: number }>,
): Array<{ name: string; total: number; failed: number }> {
  const map = new Map<string, { total: number; failed: number }>()
  for (const row of rows) {
    const bucket = map.get(row.name) ?? { total: 0, failed: 0 }
    bucket.total += row.count
    bucket.failed += row.failed
    map.set(row.name, bucket)
  }
  return Array.from(map.entries())
    .map(([name, stats]) => ({ name, ...stats }))
    .sort((a, b) => b.total - a.total)
}

export function RunInsightBreakdown({
  results,
  scenarioRows,
  agentRows,
  agentRunRows,
  activeScenarioName,
  activeScenarioId,
  onScenarioClick,
  title = 'Break down',
  scenarioCountsFromSample = false,
  windowRunTotal,
  sampleSize,
  windowDurationBuckets,
  embedded,
}: {
  results: EvaluatorResultRow[]
  scenarioRows: Array<{ name: string; scenarioId: string; count: number; failed: number; agentId: string }>
  agentRows: Array<{ id: string; name: string }>
  agentRunRows?: Array<{ id: string; name: string; total: number; failed: number }>
  activeScenarioName?: string | null
  activeScenarioId?: string | null
  onScenarioClick?: (scenarioId: string) => void
  title?: string
  /** When set, scenario counts are computed from the loaded run slice (e.g. day drill), not full-window ops rollups. */
  scenarioCountsFromSample?: boolean
  windowRunTotal?: number
  sampleSize?: number
  windowDurationBuckets?: Array<{ start_seconds: number; end_seconds: number; count: number }>
  /** When true, omit outer card chrome — use inside {@link RunInsightDrillPanel}. */
  embedded?: boolean
}) {
  const [openAgents, setOpenAgents] = useState<Set<string> | null>(null)

  const useWindowDuration = !scenarioCountsFromSample && (windowDurationBuckets?.length ?? 0) > 0
  const values = results.map((row) => row.duration_seconds).filter((value): value is number => value != null)
  const edges = [0, 60, 90, 120, 150, 180, 240]
  const buckets = useWindowDuration
    ? (windowDurationBuckets ?? []).map((bucket) => ({
      name: bucket.end_seconds >= 86_400
        ? `${bucket.start_seconds}s+`
        : `${bucket.start_seconds}–${bucket.end_seconds}s`,
      count: bucket.count,
    }))
    : edges
      .slice(0, -1)
      .map((start, index) => {
        const end = edges[index + 1]
        const count = values.filter((value) => value >= start && value < end).length
        return { name: `${start}–${end}s`, count }
      })
      .filter((bucket) => bucket.count > 0)
  const bucketMax = Math.max(...buckets.map((b) => b.count), 1)

  const byAgentDuration = new Map<string, { sum: number; count: number; failed: number }>()
  for (const row of results) {
    const name = row.agent?.name ?? row.agent_id ?? 'Unknown'
    const bucket = byAgentDuration.get(name) ?? { sum: 0, count: 0, failed: 0 }
    if (row.duration_seconds != null) {
      bucket.sum += row.duration_seconds
      bucket.count += 1
    }
    if (row.status === 'failed') bucket.failed += 1
    byAgentDuration.set(name, bucket)
  }
  const agentsDuration = Array.from(byAgentDuration.entries())
    .map(([name, stats]) => ({
      name,
      avg: stats.count ? stats.sum / stats.count : null,
      runs: stats.count,
      failed: stats.failed,
    }))
    .sort((a, b) => b.runs - a.runs)

  const scenarios = scenarioCountsFromSample
    ? (() => {
      const byScenario = new Map<string, { total: number; failed: number }>()
      for (const row of results) {
        const name = row.scenario?.name
        if (!name) continue
        const bucket = byScenario.get(name) ?? { total: 0, failed: 0 }
        bucket.total += 1
        if (row.status === 'failed') bucket.failed += 1
        byScenario.set(name, bucket)
      }
      return Array.from(byScenario.entries())
        .map(([name, stats]) => ({ name, ...stats }))
        .sort((a, b) => b.total - a.total)
    })()
    : mergeScenarioCounts(scenarioRows)
  const scenarioMax = Math.max(...scenarios.map((s) => s.total), 1)
  const sampleNote =
    !useWindowDuration
      && !scenarioCountsFromSample
      && windowRunTotal != null
      && sampleSize != null
      && sampleSize < windowRunTotal
      ? `Duration buckets use ${sampleSize.toLocaleString()} loaded runs · scenario counts are full window (${windowRunTotal.toLocaleString()}) · runs table below is complete.`
      : null

  const agentNameById = new Map(agentRows.map((row) => [row.id, row.name]))
  const scenariosByAgent = new Map<string, Array<{ name: string; scenarioId: string; count: number; failed: number }>>()
  if (scenarioCountsFromSample) {
    for (const row of results) {
      const agentKey = row.agent_id ?? row.agent?.id
      if (!agentKey) continue
      const agentName = agentNameById.get(agentKey) ?? row.agent?.name ?? 'Agent'
      const scenarioName = row.scenario?.name
      const scenarioId = row.scenario?.id
      if (!scenarioName || !scenarioId) continue
      const list = scenariosByAgent.get(agentName) ?? []
      const existing = list.find((item) => item.scenarioId === scenarioId)
      if (existing) {
        existing.count += 1
        if (row.status === 'failed') existing.failed += 1
      } else {
        list.push({
          name: scenarioName,
          scenarioId,
          count: 1,
          failed: row.status === 'failed' ? 1 : 0,
        })
      }
      scenariosByAgent.set(agentName, list)
    }
  } else {
    for (const row of scenarioRows) {
      const agentName = agentNameById.get(row.agentId) ?? 'Agent'
      const list = scenariosByAgent.get(agentName) ?? []
      list.push({ name: row.name, scenarioId: row.scenarioId, count: row.count, failed: row.failed })
      scenariosByAgent.set(agentName, list)
    }
  }
  const agentScenarioGroups = Array.from(scenariosByAgent.entries()).sort((a, b) => {
    const totalA = a[1].reduce((sum, item) => sum + item.count, 0)
    const totalB = b[1].reduce((sum, item) => sum + item.count, 0)
    return totalB - totalA
  })

  const toggleAgent = (name: string) => {
    setOpenAgents((prev) => {
      const defaultOpen = agentScenarioGroups[0]?.[0] === name
      const isOpen = prev === null ? defaultOpen : prev.has(name)
      if (prev === null) {
        const next = new Set<string>()
        for (const [agent] of agentScenarioGroups) {
          const open = agent === name ? !isOpen : agentScenarioGroups[0]?.[0] === agent
          if (open) next.add(agent)
        }
        return next
      }
      const next = new Set(prev)
      if (isOpen) next.delete(name)
      else next.add(name)
      return next
    })
  }

  if (!results.length && !scenarioRows.length) {
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-8 text-center shadow-sm">
        <p className="text-sm text-gray-500">No runs in this window for a breakdown.</p>
      </section>
    )
  }

  const selectionActive = Boolean(activeScenarioId || activeScenarioName)

  const inner = (
    <>
      <header className="mb-4 border-b border-gray-100 pb-3">
        <h3 className="text-base font-semibold text-gray-900">{title}</h3>
        <p className="mt-0.5 text-xs text-gray-500">
          {embedded
            ? 'Break down by duration and scenario — your selection filters the run list below.'
            : 'Distribution, then agents and scenarios — pick a scenario to filter runs.'}
        </p>
        {sampleNote && <p className="mt-2 text-[11px] text-amber-800/90">{sampleNote}</p>}
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-100 bg-gray-50/40 p-4">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Duration distribution</h4>
          <ul className="mt-3 space-y-2">
            {buckets.length === 0 ? (
              <li className="text-xs text-gray-400">No duration data in slice.</li>
            ) : (
              buckets.map((bucket) => (
                <li key={bucket.name} className="grid grid-cols-[5.5rem_minmax(0,1fr)_2rem] items-center gap-2 text-xs text-gray-600">
                  <span>{bucket.name}</span>
                  <span className="h-2 overflow-hidden rounded-full bg-gray-200/80">
                    <span
                      className="block h-full rounded-full bg-primary-600"
                      style={{ width: `${(bucket.count / bucketMax) * 100}%` }}
                    />
                  </span>
                  <span className="text-right tabular-nums">{bucket.count}</span>
                </li>
              ))
            )}
          </ul>
        </div>

        <div className="rounded-lg border border-gray-100 bg-gray-50/40 p-4">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">By scenario · click to filter runs</h4>
          <div className="mt-2 space-y-0.5">
            {scenarios.length === 0 ? (
              <p className="text-xs text-gray-400">No scenarios in slice.</p>
            ) : (
              scenarios.slice(0, 8).map((row) => {
                const match = scenarioRows.find((item) => item.name === row.name)
                const scenarioId = match?.scenarioId
                return (
                  <BarRow
                    key={scenarioId ?? row.name}
                    label={row.name}
                    value={row.total}
                    max={scenarioMax}
                    suffix={`${row.total} · ${row.total ? Math.round((row.failed / row.total) * 100) : 0}% fail`}
                    active={
                      (scenarioId != null && activeScenarioId === scenarioId)
                      || (scenarioId == null && activeScenarioName === row.name)
                    }
                    onClick={onScenarioClick && scenarioId ? () => onScenarioClick(scenarioId) : undefined}
                  />
                )
              })
            )}
          </div>
        </div>
      </div>

      {!scenarioCountsFromSample && (agentRunRows?.length ?? 0) > 1 ? (
        <div className="mt-6">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">By agent</h4>
          <div className="mt-2 divide-y divide-gray-100 rounded-lg border border-gray-100">
            {agentRunRows!.map((row) => (
              <div key={row.id} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
                <span className="truncate font-medium text-gray-800">{row.name}</span>
                <span className="shrink-0 text-xs text-gray-500">
                  {`${row.total} runs · ${row.total ? Math.round((row.failed / row.total) * 100) : 0}% fail`}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : agentsDuration.length > 1 ? (
        <div className="mt-6">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">By agent</h4>
          <div className="mt-2 divide-y divide-gray-100 rounded-lg border border-gray-100">
            {agentsDuration.map((row) => (
              <div key={row.name} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
                <span className="truncate font-medium text-gray-800">{row.name}</span>
                <span className="shrink-0 text-xs text-gray-500">
                  {row.avg != null ? `avg ${formatDuration(row.avg)}` : '—'}
                  {` · ${row.runs} runs`}
                  {row.failed > 0 && (
                    <span className="ml-1 text-red-700/80">{Math.round((row.failed / row.runs) * 100)}% fail</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {agentScenarioGroups.length > 0 && (
        <div className="mt-6">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Scenarios by agent · click to filter runs</h4>
          <div className="mt-2 space-y-2">
            {agentScenarioGroups.map(([agentName, rows]) => {
              const open = openAgents === null
                ? agentScenarioGroups[0]?.[0] === agentName
                : openAgents.has(agentName)
              const total = rows.reduce((sum, row) => sum + row.count, 0)
              return (
                <div key={agentName} className="overflow-hidden rounded-lg border border-gray-200">
                  <button
                    type="button"
                    onClick={() => toggleAgent(agentName)}
                    className="flex w-full items-center justify-between gap-3 bg-gray-50 px-3 py-2.5 text-left text-sm font-medium text-gray-900 hover:bg-gray-100"
                  >
                    <span>{agentName}</span>
                    <span className="text-xs font-normal text-gray-500">{total} runs</span>
                  </button>
                  {open && (
                    <ul className="divide-y divide-gray-100 bg-white px-1 py-1">
                      {rows
                        .slice()
                        .sort((a, b) => b.count - a.count)
                        .map((row) => (
                          <li key={row.scenarioId}>
                            {onScenarioClick ? (
                              <button
                                type="button"
                                onClick={() => onScenarioClick(row.scenarioId)}
                                aria-pressed={activeScenarioId === row.scenarioId}
                                className={`flex w-full items-center justify-between gap-3 rounded-md border px-2 py-2 text-left text-sm transition-colors ${activeScenarioId === row.scenarioId
                                  ? 'border-primary-200 bg-primary-50 font-medium text-primary-900'
                                  : 'border-transparent text-gray-700 hover:border-gray-200 hover:bg-gray-50'
                                  }`}
                              >
                                <span className="flex min-w-0 items-center gap-2 truncate">
                                  {activeScenarioId === row.scenarioId ? (
                                    <ChevronDown className="h-3.5 w-3.5 shrink-0 rotate-[-90deg] text-primary-700" aria-hidden />
                                  ) : null}
                                  <span className="truncate">{row.name}</span>
                                </span>
                                <span className="shrink-0 text-xs text-gray-500">
                                  {row.count} · {row.count ? Math.round((row.failed / row.count) * 100) : 0}% fail
                                </span>
                              </button>
                            ) : (
                              <div className="flex items-center justify-between gap-3 px-2 py-2 text-sm text-gray-700">
                                <span className="truncate">{row.name}</span>
                                <span className="shrink-0 text-xs text-gray-500">
                                  {row.count} · {row.count ? Math.round((row.failed / row.count) * 100) : 0}% fail
                                </span>
                              </div>
                            )}
                          </li>
                        ))}
                    </ul>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {embedded && onScenarioClick && selectionActive && (
        <p className="mt-5 flex items-center gap-2 text-[11px] font-medium text-primary-900/80">
          <span className="h-px flex-1 bg-primary-200/80" aria-hidden />
          Run list below matches this selection
          <ChevronDown className="h-3.5 w-3.5 text-primary-700" aria-hidden />
          <span className="h-px flex-1 bg-primary-200/80" aria-hidden />
        </p>
      )}
    </>
  )

  if (embedded) {
    return <div className="p-5">{inner}</div>
  }

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      {inner}
    </section>
  )
}

export function RunInsightDrillPanel({
  filterBar,
  breakdown,
  runsTitle,
  runsSubtitle,
  runs,
  selectionActive,
}: {
  filterBar: ReactNode
  breakdown: ReactNode
  runsTitle: string
  runsSubtitle?: string
  runs: ReactNode
  selectionActive: boolean
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-100 bg-gray-50/60 px-5 py-3">{filterBar}</div>
      {breakdown}
      <div
        className={`border-t-2 ${selectionActive ? 'border-primary-200 bg-primary-50/25' : 'border-gray-200 bg-gray-50/40'}`}
      >
        <header className="flex flex-wrap items-start justify-between gap-2 border-b border-gray-100 px-5 py-3">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
              {selectionActive ? 'Filtered run list' : 'All runs in this window'}
            </p>
            <h3 className="text-sm font-semibold text-gray-900">{runsTitle}</h3>
            {runsSubtitle ? <p className="mt-0.5 text-xs text-gray-500">{runsSubtitle}</p> : null}
          </div>
        </header>
        <div className="px-3 pb-4 pt-1 sm:px-5 sm:pb-5">{runs}</div>
      </div>
    </section>
  )
}

export function RunInsightRunsSection({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <section className="space-y-3">
      {title ? (
        <header>
          <h3 className="text-base font-semibold text-gray-900">{title}</h3>
        </header>
      ) : null}
      {children}
    </section>
  )
}

export function usesRunInsightLayout(widgetType: string | undefined): boolean {
  return widgetType === 'avg_duration' || widgetType === 'scenarios' || widgetType === 'scenarios_by_agent'
}
